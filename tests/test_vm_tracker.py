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


class TestGetVmAgeMinutes:
    def test_returns_positive_age_for_tracked_vm(self, tracker):
        """get_vm_age_minutes 对已追踪的 VM 返回正数分钟数。"""
        old_time = (datetime.now() - timedelta(minutes=5)).isoformat()
        tracker.track_vm(500, owner="alice", created_at=old_time)
        age = tracker.get_vm_age_minutes(500)
        assert age >= 5.0

    def test_returns_zero_for_untracked_vm(self, tracker):
        """get_vm_age_minutes 对未追踪的 VM 返回 0.0，不抛异常。"""
        assert tracker.get_vm_age_minutes(999) == 0.0

    def test_returns_zero_for_invalid_created_at(self, tracker):
        """get_vm_age_minutes 遇到无效 created_at 时返回 0.0，不抛异常（回归）。"""
        import json
        tracker.data_file.write_text(json.dumps({
            "500": {"created_at": "NOT_A_DATE", "owner": "alice"}
        }))
        assert tracker.get_vm_age_minutes(500) == 0.0

    def test_legacy_string_format_returns_positive_age(self, tracker):
        """旧格式（纯字符串 created_at）时 get_vm_age_minutes 也应返回正确年龄。"""
        import json
        old_time = (datetime.now() - timedelta(minutes=3)).isoformat()
        tracker.data_file.write_text(json.dumps({"500": old_time}))
        age = tracker.get_vm_age_minutes(500)
        assert age >= 3.0


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

    def test_legacy_string_format_owner_is_unknown(self, tracker):
        """旧格式（纯字符串值）的 VM 在 get_all_vms_with_details 中 owner 应为 'unknown'。"""
        import json
        old_time = (datetime.now() - timedelta(minutes=2)).isoformat()
        tracker.data_file.write_text(json.dumps({"500": old_time}))
        details = tracker.get_all_vms_with_details()
        assert len(details) == 1
        assert details[0]["owner"] == "unknown"
        assert details[0]["created_at"] == old_time

    def test_invalid_created_at_yields_zero_age(self, tracker):
        """get_all_vms_with_details 遇到无效 created_at 时 age_minutes 为 0.0，不抛异常。"""
        import json
        tracker.data_file.write_text(json.dumps({
            "500": {"created_at": "INVALID", "owner": "alice"}
        }))
        details = tracker.get_all_vms_with_details()
        assert details[0]["age_minutes"] == 0.0


class TestTemplateSafety:
    def test_template_id_not_auto_claimable(self, tracker):
        """Template VM should never appear as user-owned via auto-claim."""
        from backend import config
        # Template VM is never tracked in normal operations
        assert tracker.get_vm_owner(config.VM_TEMPLATE_ID) is None


class TestOldFormatMigration:
    def test_track_vm_preserves_old_created_at(self, tracker):
        """旧格式（纯字符串）迁移时 created_at 不得丢失（B 回归）"""
        old_time = "2026-01-15T10:00:00"
        # 手动写入旧格式数据
        import json
        tracker.data_file.write_text(json.dumps({"500": old_time}))

        # 调用 track_vm 触发迁移（同一 VM，新的 owner）
        tracker.track_vm(500, owner="alice")

        # 迁移后 created_at 必须保留旧时间，不能被 now() 覆盖
        all_vms = tracker.get_all_tracked_vms()
        assert 500 in all_vms
        assert all_vms[500] == datetime.fromisoformat(old_time), (
            "track_vm() must preserve original created_at when migrating old-format entries"
        )

    def test_track_vm_old_format_owner_updated(self, tracker):
        """旧格式迁移后 owner 正确设置"""
        import json
        old_time = "2026-01-15T10:00:00"
        tracker.data_file.write_text(json.dumps({"500": old_time}))

        tracker.track_vm(500, owner="alice")

        assert tracker.get_vm_owner(500) == "alice"

    def test_track_new_vm_uses_provided_created_at(self, tracker):
        """全新 VM 使用调用方传入的 created_at"""
        t = "2026-02-01T08:00:00"
        tracker.track_vm(501, owner="bob", created_at=t)
        all_vms = tracker.get_all_tracked_vms()
        assert all_vms[501] == datetime.fromisoformat(t)


class TestCorruptedData:
    """I 回归：_load_data 对损坏文件中的非数字 key 应跳过而不崩溃。"""

    def test_non_digit_key_is_skipped(self, tracker):
        """文件中的非数字 key 应被过滤掉，不应抛出 ValueError（I 回归）。"""
        import json
        corrupted = {
            "500": {"created_at": "2026-01-01T00:00:00", "owner": "alice"},
            "not-a-number": {"created_at": "2026-01-01T00:00:00", "owner": "bob"},
            "abc": "2026-01-01T00:00:00",
        }
        tracker.data_file.write_text(json.dumps(corrupted))
        data = tracker._load_data()
        assert 500 in data
        assert "not-a-number" not in data
        assert "abc" not in data

    def test_corrupted_file_does_not_crash_get_owner(self, tracker):
        """损坏数据下 get_vm_owner 应正常返回，不抛异常（I 回归）。"""
        import json
        corrupted = {
            "500": {"created_at": "2026-01-01T00:00:00", "owner": "alice"},
            "bad-key": "some-value",
        }
        tracker.data_file.write_text(json.dumps(corrupted))
        assert tracker.get_vm_owner(500) == "alice"
        # Non-digit key must not surface as a VM
        assert tracker.get_vm_owner(0) is None
