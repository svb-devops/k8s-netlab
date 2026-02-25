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
