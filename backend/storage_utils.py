"""
K8S NetLab - Safe JSON Storage Utilities

Provides atomic read/write/update operations for JSON data files.
All operations use a per-file lock file to prevent concurrent corruption.

Usage:
    from backend.storage_utils import safe_read_json, safe_write_json, safe_update_json

    # Read
    data = safe_read_json(USERS_FILE, default={})

    # Overwrite
    safe_write_json(USERS_FILE, data)

    # Read-modify-write atomically
    def add_user(users):
        users["alice"] = {...}
        return users
    safe_update_json(USERS_FILE, add_user)
"""

import fcntl
import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@contextmanager
def _file_lock(path: Path, exclusive: bool):
    """
    Acquire a flock-based lock on a dedicated .lock file.

    Using a separate lock file (not the data file itself) means the lock
    survives atomic renames and is never accidentally cleared by writers.
    """
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with open(lock_path, "w") as lf:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lf, mode)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def safe_read_json(path: Path, default: Optional[Dict] = None) -> Dict:
    """
    Read a JSON file under a shared lock.

    Args:
        path:    Path to the JSON file.
        default: Value to return if file is missing or unreadable.

    Returns:
        Parsed dict, or *default* on error.
    """
    if default is None:
        default = {}

    if not path.exists():
        return default

    try:
        with _file_lock(path, exclusive=False):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"safe_read_json({path.name}): {e}")
        return default


def safe_write_json(path: Path, data: Any) -> bool:
    """
    Write *data* to a JSON file atomically under an exclusive lock.

    The write goes to a temporary file first; on success it is renamed
    over the target (atomic on Linux, same filesystem).

    Args:
        path: Path to the JSON file.
        data: JSON-serialisable object.

    Returns:
        True on success, False on error.
    """
    tmp = path.with_suffix(".tmp")

    try:
        with _file_lock(path, exclusive=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)  # atomic on same filesystem
        return True
    except Exception as e:
        logger.error(f"safe_write_json({path.name}): {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def safe_update_json(
    path: Path,
    updater: Callable[[Dict], Dict],
    default: Optional[Dict] = None,
) -> bool:
    """
    Read-modify-write a JSON file atomically under an exclusive lock.

    The entire read → transform → write cycle runs while holding the
    exclusive lock, so no other process can interleave.

    Args:
        path:    Path to the JSON file.
        updater: Function that receives the current dict and returns
                 the updated dict.
        default: Starting value when the file is missing or empty.

    Returns:
        True on success, False on error.
    """
    if default is None:
        default = {}

    tmp = path.with_suffix(".tmp")

    try:
        with _file_lock(path, exclusive=True):
            path.parent.mkdir(parents=True, exist_ok=True)

            if path.exists():
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                except Exception:
                    data = dict(default)
            else:
                data = dict(default)

            data = updater(data)

            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        return True
    except Exception as e:
        logger.error(f"safe_update_json({path.name}): {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False
