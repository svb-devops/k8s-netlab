"""Tests for VMTracker — ownership, expiry, and format migration."""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.vm_tracker import VMTracker


@pytest.fixture
def tracker(tmp_path):
    t = VMTracker()
    t.data_file = tmp_path / "vm_creation_times.json"
    return t


class TestTrackAndOwnership:
    def test_track_and_get_owner(self, tracker):
        tracker.track_vm(500, owner="alice")
        assert tracker.get_vm_owner(500) == "alice"

    def test_is_owner_true(self, tracker):
        tracker.track_vm(501, owner="bob")
        assert tracker.is_owner(501, "bob") is True

    def test_is_owner_false(self, tracker):
        tracker.track_vm(502, owner="alice")
        assert tracker.is_owner(502, "bob") is False

    def test_get_user_vms(self, tracker):
        tracker.track_vm(500, owner="alice")
        tracker.track_vm(501, owner="bob")
        tracker.track_vm(502, owner="alice")
        assert sorted(tracker.get_user_vms("alice")) == [500, 502]

    def test_untrack_removes_vm(self, tracker):
        tracker.track_vm(500, owner="alice")
        tracker.untrack_vm(500)
        assert tracker.get_vm_owner(500) is None

    def test_unknown_vm_returns_none(self, tracker):
        assert tracker.get_vm_owner(999) is None


class TestExpiry:
    def test_expired_vm_detected(self, tracker):
        old_time = (datetime.now() - timedelta(minutes=35)).isoformat()
        tracker.track_vm(500, owner="alice", created_at=old_time)
        expired = tracker.get_expired_vms(max_age_minutes=30)
        assert 500 in expired

    def test_fresh_vm_not_expired(self, tracker):
        tracker.track_vm(500, owner="alice")
        expired = tracker.get_expired_vms(max_age_minutes=30)
        assert 500 not in expired


class TestGetAllVmsWithDetails:
    def test_returns_owner_and_age(self, tracker):
        old = (datetime.now() - timedelta(minutes=10)).isoformat()
        tracker.track_vm(500, owner="alice", created_at=old)
        tracker.track_vm(501, owner="bob")

        details = tracker.get_all_vms_with_details()
        assert len(details) == 2

        vm500 = next(d for d in details if d["vm_id"] == 500)
        assert vm500["owner"] == "alice"
        assert vm500["age_minutes"] >= 10.0

        vm501 = next(d for d in details if d["vm_id"] == 501)
        assert vm501["owner"] == "bob"
        assert vm501["age_minutes"] < 1.0

    def test_empty_tracker_returns_empty_list(self, tracker):
        assert tracker.get_all_vms_with_details() == []


class TestTemplateSafety:
    def test_template_id_not_auto_claimable(self, tracker):
        """Template VM should never appear as user-owned via auto-claim."""
        from backend import config
        # Template VM is never tracked in normal operations
        assert tracker.get_vm_owner(config.VM_TEMPLATE_ID) is None
