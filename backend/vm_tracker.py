"""
K8S NetLab - VM Creation Time Tracker

Tracks VM creation times for automatic cleanup.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from backend.storage_utils import safe_read_json, safe_update_json, safe_write_json

logger = logging.getLogger(__name__)

# Data file path
DATA_DIR = Path(__file__).parent.parent / "data"
TRACKER_FILE = DATA_DIR / "vm_creation_times.json"


class VMTracker:
    """Tracks VM creation times for automatic cleanup."""

    def __init__(self):
        """Initialize VM tracker."""
        self.data_file = TRACKER_FILE
        DATA_DIR.mkdir(exist_ok=True)

    def _load_data(self) -> Dict[int, str]:
        """Load VM creation times from file (string keys → int keys)."""
        raw = safe_read_json(self.data_file, default={})
        return {int(k): v for k, v in raw.items()}

    def _save_data(self, data: Dict[int, str]):
        """Save VM creation times to file."""
        safe_write_json(self.data_file, data)

    def track_vm(self, vm_id: int, owner: str, created_at: Optional[str] = None):
        """
        Track a VM creation time and owner.

        Args:
            vm_id: VM ID
            owner: Username of VM owner
            created_at: ISO format timestamp (default: now)
        """
        if created_at is None:
            created_at = datetime.now().isoformat()

        def _track(data: Dict) -> Dict:
            # Migrate old format (plain string) to new format (dict)
            if isinstance(data.get(str(vm_id)), str):
                data[str(vm_id)] = {
                    "created_at": data[str(vm_id)],
                    "owner": "unknown",
                }
            data[str(vm_id)] = {"created_at": created_at, "owner": owner}
            return data

        safe_update_json(self.data_file, _track)
        logger.info(f"Tracking VM {vm_id} created by {owner} at {created_at}")

    def untrack_vm(self, vm_id: int):
        """
        Remove VM from tracking.

        Args:
            vm_id: VM ID
        """
        def _untrack(data: Dict) -> Dict:
            data.pop(str(vm_id), None)
            data.pop(vm_id, None)  # handle any legacy int keys in file
            return data

        safe_update_json(self.data_file, _untrack)
        logger.info(f"Untracked VM {vm_id}")

    def get_all_tracked_vms(self) -> Dict[int, datetime]:
        """
        Get all tracked VMs with their creation times.

        Returns:
            Dict mapping VM ID to creation datetime
        """
        data = self._load_data()
        result = {}

        for vm_id, vm_data in data.items():
            try:
                # Support both old (string) and new (dict) formats
                if isinstance(vm_data, str):
                    created_at = datetime.fromisoformat(vm_data)
                else:
                    created_at = datetime.fromisoformat(vm_data["created_at"])
                result[vm_id] = created_at
            except (ValueError, KeyError) as e:
                logger.warning(f"Invalid data for VM {vm_id}: {e}")

        return result

    def get_vm_owner(self, vm_id: int) -> Optional[str]:
        """
        Get the owner of a VM.

        Args:
            vm_id: VM ID

        Returns:
            Username of owner, or None if not found
        """
        data = self._load_data()

        if vm_id not in data:
            return None

        vm_data = data[vm_id]

        if isinstance(vm_data, str):
            return "unknown"  # old format
        return vm_data.get("owner", "unknown")

    def is_owner(self, vm_id: int, username: str) -> bool:
        """
        Check if user is the owner of a VM.

        Args:
            vm_id: VM ID
            username: Username to check

        Returns:
            True if user owns the VM
        """
        return self.get_vm_owner(vm_id) == username

    def get_user_vms(self, username: str) -> list[int]:
        """
        Get all VMs owned by a user.

        Args:
            username: Username

        Returns:
            List of VM IDs owned by the user
        """
        data = self._load_data()
        return [
            int(vm_id)
            for vm_id, vm_data in data.items()
            if isinstance(vm_data, dict) and vm_data.get("owner") == username
        ]

    def get_all_vms_with_details(self) -> list:
        """
        Return all tracked VMs with full detail.

        Returns:
            List of dicts: {vm_id, owner, created_at, age_minutes}
        """
        raw = self._load_data()
        now = datetime.now()
        result = []
        for vm_id, vm_data in raw.items():
            if isinstance(vm_data, str):
                created_at_str = vm_data
                owner = "unknown"
            else:
                created_at_str = vm_data.get("created_at", "")
                owner = vm_data.get("owner", "unknown")
            try:
                age_minutes = round(
                    (now - datetime.fromisoformat(created_at_str)).total_seconds() / 60, 1
                )
            except (ValueError, TypeError):
                age_minutes = 0.0
            result.append({
                "vm_id": int(vm_id),
                "owner": owner,
                "created_at": created_at_str,
                "age_minutes": age_minutes,
            })
        return result

    def get_vm_age_minutes(self, vm_id: int) -> float:
        """Return age in minutes of a tracked VM, or 0.0 if not found."""
        data = self._load_data()
        vm_data = data.get(vm_id)
        if vm_data is None:
            return 0.0
        try:
            if isinstance(vm_data, str):
                created_at = datetime.fromisoformat(vm_data)
            else:
                created_at = datetime.fromisoformat(vm_data["created_at"])
            return (datetime.now() - created_at).total_seconds() / 60
        except (ValueError, KeyError):
            return 0.0

    def get_expired_vms(self, max_age_minutes: int = 30) -> list[int]:
        """
        Get list of VMs that exceeded max age.

        Args:
            max_age_minutes: Maximum age in minutes (default: 30)

        Returns:
            List of VM IDs that should be deleted
        """
        now = datetime.now()
        expired = []

        for vm_id, created_at in self.get_all_tracked_vms().items():
            age_minutes = (now - created_at).total_seconds() / 60
            if age_minutes > max_age_minutes:
                expired.append(vm_id)
                logger.info(f"VM {vm_id} expired ({age_minutes:.1f} minutes old)")

        return expired


# Global tracker instance
vm_tracker = VMTracker()
