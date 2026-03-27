"""
Tests for backend/config.py

Verifies environment variable loading, type conversion,
and fail-fast behavior for missing required variables.
"""

import os
import pytest


class TestGetRequiredEnv:
    """Tests for _get_required_env()"""

    def test_returns_value_when_set(self, monkeypatch):
        """Required env var returns its value when set."""
        monkeypatch.setenv("PROXMOX_HOST", "192.168.1.10")
        from backend.config import _get_required_env
        assert _get_required_env("PROXMOX_HOST") == "192.168.1.10"

    def test_raises_when_missing(self, monkeypatch):
        """Required env var raises RuntimeError when missing."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        from backend.config import _get_required_env
        with pytest.raises(RuntimeError, match="Missing required environment variable"):
            _get_required_env("MISSING_VAR")

    def test_raises_when_empty(self, monkeypatch):
        """Required env var raises RuntimeError when empty string."""
        monkeypatch.setenv("EMPTY_VAR", "")
        from backend.config import _get_required_env
        with pytest.raises(RuntimeError, match="Missing required environment variable"):
            _get_required_env("EMPTY_VAR")


class TestGetEnvInt:
    """Tests for _get_env_int()"""

    def test_returns_default_when_not_set(self, monkeypatch):
        """Returns default when env var is not set."""
        monkeypatch.delenv("TEST_PORT", raising=False)
        from backend.config import _get_env_int
        assert _get_env_int("TEST_PORT", 8006) == 8006

    def test_parses_valid_integer(self, monkeypatch):
        """Parses a valid integer string."""
        monkeypatch.setenv("TEST_PORT", "9090")
        from backend.config import _get_env_int
        assert _get_env_int("TEST_PORT", 8006) == 9090

    def test_raises_on_invalid_integer(self, monkeypatch):
        """Raises ValueError for non-integer string."""
        monkeypatch.setenv("TEST_PORT", "not_a_number")
        from backend.config import _get_env_int
        with pytest.raises(ValueError, match="must be an integer"):
            _get_env_int("TEST_PORT", 8006)


class TestGetEnvBool:
    """Tests for _get_env_bool()"""

    def test_returns_default_when_not_set(self, monkeypatch):
        """Returns default when env var is not set."""
        monkeypatch.delenv("TEST_BOOL", raising=False)
        from backend.config import _get_env_bool
        assert _get_env_bool("TEST_BOOL", False) is False

    def test_true_values(self, monkeypatch):
        """Recognizes 'true', '1', 'yes' as True."""
        from backend.config import _get_env_bool
        for val in ("true", "True", "TRUE", "1", "yes", "Yes"):
            monkeypatch.setenv("TEST_BOOL", val)
            assert _get_env_bool("TEST_BOOL", False) is True

    def test_false_values(self, monkeypatch):
        """Anything else is False."""
        from backend.config import _get_env_bool
        for val in ("false", "0", "no", "random"):
            monkeypatch.setenv("TEST_BOOL", val)
            assert _get_env_bool("TEST_BOOL", True) is False


class TestConfigCrossValidation:
    """G 回归：启动时配置交叉校验，防止静默冲突。"""

    def _pop_config(self, monkeypatch):
        import sys
        if "backend.config" in sys.modules:
            monkeypatch.setitem(sys.modules, "backend.config", sys.modules["backend.config"])
        sys.modules.pop("backend.config", None)

    def test_template_id_inside_vm_range_raises(self, monkeypatch):
        """VM_TEMPLATE_ID 落在 VM_ID_MIN..MAX 范围内时应在启动时抛 RuntimeError（G 回归）。"""
        self._pop_config(monkeypatch)
        monkeypatch.setenv("VM_TEMPLATE_ID", "500")
        monkeypatch.setenv("VM_ID_MIN", "500")
        monkeypatch.setenv("VM_ID_MAX", "599")
        with pytest.raises(RuntimeError, match="VM_TEMPLATE_ID"):
            import backend.config  # noqa: F401

    def test_max_vms_per_user_exceeds_total_raises(self, monkeypatch):
        """MAX_VMS_PER_USER > MAX_TOTAL_VMS 时应在启动时抛 RuntimeError（G 回归）。"""
        self._pop_config(monkeypatch)
        monkeypatch.setenv("MAX_VMS_PER_USER", "10")
        monkeypatch.setenv("MAX_TOTAL_VMS", "5")
        with pytest.raises(RuntimeError, match="MAX_VMS_PER_USER"):
            import backend.config  # noqa: F401

class TestModuleLoadFailsFast:
    """Test that importing config module fails without required env vars."""

    def test_import_fails_without_required_vars(self, monkeypatch):
        """Module import raises RuntimeError if PROXMOX_HOST is missing."""
        import sys
        monkeypatch.delenv("PROXMOX_HOST", raising=False)
        monkeypatch.delenv("PROXMOX_USER", raising=False)
        monkeypatch.delenv("PROXMOX_PASSWORD", raising=False)
        # Save current module so monkeypatch restores it after the test.
        # Without this, sys.modules loses the entry and other tests that
        # monkeypatch config attributes get a fresh module object that
        # isn't shared with already-imported modules (e.g. vm_manager).
        if "backend.config" in sys.modules:
            monkeypatch.setitem(sys.modules, "backend.config", sys.modules["backend.config"])
        sys.modules.pop("backend.config", None)
        with pytest.raises(RuntimeError, match="Missing required environment variable"):
            import backend.config  # noqa: F401
