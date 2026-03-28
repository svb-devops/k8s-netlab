"""
Tests for backend.storage_utils

Covers:
  - basic read / write / update
  - missing-file defaults
  - atomic write (no partial reads)
  - concurrent writers don't corrupt data
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.storage_utils import safe_read_json, safe_update_json, safe_write_json


@pytest.fixture
def tmp_json(tmp_path):
    """Return a Path inside a temp directory (file does not exist yet)."""
    return tmp_path / "data.json"


# ---------------------------------------------------------------------------
# Basic functionality
# ---------------------------------------------------------------------------

class TestSafeReadJson:
    def test_missing_file_returns_default(self, tmp_json):
        result = safe_read_json(tmp_json)
        assert result == {}

    def test_missing_file_returns_custom_default(self, tmp_json):
        result = safe_read_json(tmp_json, default={"k": 1})
        assert result == {"k": 1}

    def test_reads_existing_file(self, tmp_json):
        tmp_json.write_text(json.dumps({"a": 1}))
        assert safe_read_json(tmp_json) == {"a": 1}

    def test_corrupt_json_returns_default(self, tmp_json):
        """safe_read_json 读取损坏的 JSON 时必须返回 default，不抛异常（回归：数据层静默丢失）。"""
        tmp_json.write_text("{ not valid json !!!")
        result = safe_read_json(tmp_json, default={"fallback": True})
        assert result == {"fallback": True}


class TestSafeWriteJson:
    def test_creates_file(self, tmp_json):
        safe_write_json(tmp_json, {"x": 42})
        assert tmp_json.exists()
        assert json.loads(tmp_json.read_text()) == {"x": 42}

    def test_overwrites_existing(self, tmp_json):
        tmp_json.write_text(json.dumps({"old": True}))
        safe_write_json(tmp_json, {"new": True})
        assert json.loads(tmp_json.read_text()) == {"new": True}

    def test_returns_true_on_success(self, tmp_json):
        assert safe_write_json(tmp_json, {}) is True

    def test_no_tmp_file_left_behind(self, tmp_path, tmp_json):
        safe_write_json(tmp_json, {"v": 1})
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    def test_returns_false_on_os_error(self, tmp_json):
        """safe_write_json 在 os.replace 失败时必须返回 False，不抛异常（回归：写失败静默丢失）。"""
        with patch("backend.storage_utils.os.replace", side_effect=OSError("disk full")):
            result = safe_write_json(tmp_json, {"v": 1})
        assert result is False

    def test_no_tmp_file_left_after_failure(self, tmp_path, tmp_json):
        """safe_write_json 写失败后必须清理 .tmp 临时文件，不留残余。"""
        with patch("backend.storage_utils.os.replace", side_effect=OSError("disk full")):
            safe_write_json(tmp_json, {"v": 1})
        assert list(tmp_path.glob("*.tmp")) == []

    def test_returns_false_even_when_cleanup_also_fails(self, tmp_json):
        """os.replace 失败 + tmp.unlink 也失败时，safe_write_json 仍必须返回 False 不抛异常。"""
        with patch("backend.storage_utils.os.replace", side_effect=OSError("disk full")), \
             patch("pathlib.Path.unlink", side_effect=OSError("unlink failed")):
            result = safe_write_json(tmp_json, {"v": 1})
        assert result is False


class TestSafeUpdateJson:
    def test_creates_file_from_default(self, tmp_json):
        safe_update_json(tmp_json, lambda d: {**d, "created": True})
        assert json.loads(tmp_json.read_text())["created"] is True

    def test_updates_existing(self, tmp_json):
        tmp_json.write_text(json.dumps({"count": 0}))
        safe_update_json(tmp_json, lambda d: {**d, "count": d["count"] + 1})
        assert json.loads(tmp_json.read_text())["count"] == 1

    def test_returns_true_on_success(self, tmp_json):
        assert safe_update_json(tmp_json, lambda d: d) is True

    def test_corrupt_existing_file_falls_back_to_default(self, tmp_json):
        """safe_update_json 读到损坏的 JSON 时必须用 default 继续，不抛异常（回归：update 失败静默丢失）。"""
        tmp_json.write_text("{ broken json")
        result = safe_update_json(tmp_json, lambda d: {**d, "fixed": True}, default={"seed": 1})
        assert result is True
        assert json.loads(tmp_json.read_text()) == {"seed": 1, "fixed": True}

    def test_returns_false_when_updater_raises(self, tmp_json):
        """safe_update_json 的 updater 抛异常时必须返回 False，不抛异常（回归：异常逃逸）。"""
        def bad_updater(d):
            raise ValueError("updater bug")

        result = safe_update_json(tmp_json, bad_updater)
        assert result is False

    def test_no_tmp_file_left_after_failure(self, tmp_path, tmp_json):
        """safe_update_json 失败后必须清理 .tmp 临时文件。"""
        with patch("backend.storage_utils.os.replace", side_effect=OSError("disk full")):
            result = safe_update_json(tmp_json, lambda d: d)
        assert result is False
        assert list(tmp_path.glob("*.tmp")) == []

    def test_returns_false_even_when_cleanup_also_fails(self, tmp_json):
        """os.replace 失败 + tmp.unlink 也失败时，safe_update_json 仍必须返回 False 不抛异常。"""
        with patch("backend.storage_utils.os.replace", side_effect=OSError("disk full")), \
             patch("pathlib.Path.unlink", side_effect=OSError("unlink failed")):
            result = safe_update_json(tmp_json, lambda d: d)
        assert result is False


# ---------------------------------------------------------------------------
# Concurrent writers
# ---------------------------------------------------------------------------

def _increment(path: Path, iterations: int):
    for _ in range(iterations):
        safe_update_json(path, lambda d: {**d, "n": d.get("n", 0) + 1})


class TestConcurrentAccess:
    def test_no_corruption_under_concurrent_writers(self, tmp_json):
        safe_write_json(tmp_json, {"n": 0})

        threads = [
            threading.Thread(target=_increment, args=(tmp_json, 20))
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = safe_read_json(tmp_json)
        assert final["n"] == 100, f"Expected 100, got {final['n']} (data race?)"

    def test_concurrent_reads_and_writes(self, tmp_json):
        safe_write_json(tmp_json, {"n": 0})
        errors = []

        def reader():
            for _ in range(50):
                data = safe_read_json(tmp_json)
                try:
                    assert isinstance(data, dict)
                    assert "n" in data
                except AssertionError as e:
                    errors.append(str(e))

        threads = (
            [threading.Thread(target=_increment, args=(tmp_json, 10)) for _ in range(3)]
            + [threading.Thread(target=reader) for _ in range(3)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Read errors: {errors}"
