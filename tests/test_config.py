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


class TestModuleLoadFailsFast:
    """Test that importing config module fails without required env vars."""

    def test_import_fails_without_required_vars(self, monkeypatch):
        """Module import raises RuntimeError if PROXMOX_HOST is missing."""
        import sys
        monkeypatch.delenv("PROXMOX_HOST", raising=False)
        monkeypatch.delenv("PROXMOX_USER", raising=False)
        monkeypatch.delenv("PROXMOX_PASSWORD", raising=False)
        # Remove cached module so it re-evaluates on import
        sys.modules.pop("backend.config", None)
        with pytest.raises(RuntimeError, match="Missing required environment variable"):
            import backend.config  # noqa: F401
