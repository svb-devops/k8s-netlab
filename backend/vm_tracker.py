"""
K8S NetLab - VM Creation Time Tracker

Tracks VM creation times for automatic cleanup.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Data file path
DATA_DIR = Path(__file__).parent.parent / "data"
TRACKER_FILE = DATA_DIR / "vm_creation_times.json"


class VMTracker:
    """Tracks VM creation times for automatic cleanup."""

    def __init__(self):
        """Initialize VM tracker."""
        self.data_file = TRACKER_FILE
        self._ensure_data_dir()
        self._load_data()

    def _ensure_data_dir(self):
        """Ensure data directory exists."""
        DATA_DIR.mkdir(exist_ok=True)

    def _load_data(self) -> Dict[int, str]:
        """Load VM creation times from file."""
        if not self.data_file.exists():
            return {}

        try:
            with open(self.data_file, "r") as f:
                data = json.load(f)
                # Convert string keys to int
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to load VM tracker data: {e}")
            return {}

    def _save_data(self, data: Dict[int, str]):
        """Save VM creation times to file."""
        try:
            with open(self.data_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save VM tracker data: {e}")

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

        data = self._load_data()
        # Store as dict with owner and created_at
        if isinstance(data.get(vm_id), str):
            # Migrate old format (string) to new format (dict)
            data[vm_id] = {
                "created_at": data[vm_id],
                "owner": "unknown"
            }

        data[vm_id] = {
            "created_at": created_at,
            "owner": owner
        }
        self._save_data(data)

        logger.info(f"Tracking VM {vm_id} created by {owner} at {created_at}")

    def untrack_vm(self, vm_id: int):
        """
        Remove VM from tracking.

        Args:
            vm_id: VM ID
        """
        data = self._load_data()
        if vm_id in data:
            del data[vm_id]
            self._save_data(data)
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

        # Support both old (string) and new (dict) formats
        if isinstance(vm_data, str):
            return "unknown"  # Old format, no owner info
        else:
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
        owner = self.get_vm_owner(vm_id)
        return owner == username

    def get_user_vms(self, username: str) -> list[int]:
        """
        Get all VMs owned by a user.

        Args:
            username: Username

        Returns:
            List of VM IDs owned by the user
        """
        data = self._load_data()
        user_vms = []

        for vm_id, vm_data in data.items():
            # Support both old (string) and new (dict) formats
            if isinstance(vm_data, dict):
                if vm_data.get("owner") == username:
                    user_vms.append(int(vm_id))

        return user_vms

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
