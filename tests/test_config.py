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

    def test_short_admin_token_raises(self, monkeypatch):
        """ADMIN_TOKEN 短于 32 字符时应在启动时抛 RuntimeError（H3 回归）。"""
        self._pop_config(monkeypatch)
        monkeypatch.setenv("ADMIN_TOKEN", "tooshort")  # < 32 chars
        with pytest.raises(RuntimeError, match="ADMIN_TOKEN"):
            import backend.config  # noqa: F401


def test_http_registry_mirror_logs_warning(monkeypatch, caplog):
    """VM_REGISTRY_MIRROR 未设置时应记录不安全 HTTP fallback 警告（H1 回归）。"""
    import logging
    from backend import config
    monkeypatch.setattr(config, "VM_REGISTRY_MIRROR", "")
    with caplog.at_level(logging.WARNING, logger="backend.config"):
        config._warn_insecure_defaults()
    assert "VM_REGISTRY_MIRROR" in caplog.text
    assert "insecure" in caplog.text.lower()


def _pop_config(monkeypatch):
    """
    Remove backend.config from sys.modules so next import re-executes module-level code.

    Also saves/restores the `config` attribute on the `backend` package object, which
    Python updates as a side-effect of `import backend.config`. Without this,
    `from backend import config` in other modules would get the freshly-created module
    object instead of the original, causing cross-test fixture patching to target the
    wrong object.
    """
    import sys
    import backend as _backend_pkg
    if "backend.config" in sys.modules:
        monkeypatch.setitem(sys.modules, "backend.config", sys.modules["backend.config"])
    # Preserve the package-level attribute so it is restored after the test
    if hasattr(_backend_pkg, "config"):
        monkeypatch.setattr(_backend_pkg, "config", _backend_pkg.config)
    sys.modules.pop("backend.config", None)


def _base_env(monkeypatch):
    """Set minimal env vars required for a clean config import."""
    monkeypatch.setenv("PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "user@pve!tok")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret-token")
    monkeypatch.delenv("PROXMOX_USER", raising=False)
    monkeypatch.delenv("PROXMOX_PASSWORD", raising=False)
    monkeypatch.setenv("VM_SSH_PASSWORD", "ssh-pass")
    monkeypatch.setenv("ADMIN_TOKEN", "a" * 32)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)


def test_proxmox_password_auth_path(monkeypatch):
    """PROXMOX_USER + PROXMOX_PASSWORD（无 token）时 config 应正常加载（旧版认证回归）。"""
    _pop_config(monkeypatch)
    monkeypatch.setenv("PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setenv("VM_SSH_PASSWORD", "ssh-pass")
    monkeypatch.setenv("ADMIN_TOKEN", "a" * 32)
    monkeypatch.delenv("PROXMOX_TOKEN_ID", raising=False)
    monkeypatch.delenv("PROXMOX_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("PROXMOX_USER", "root@pam")
    monkeypatch.setenv("PROXMOX_PASSWORD", "proxmox-pass")

    import backend.config as cfg
    assert cfg._proxmox_auth_method == "password"


def test_allowed_origins_logs_info(monkeypatch, caplog):
    """ALLOWED_ORIGINS 已设置时 config 应记录 info 日志（CORS 配置生效回归）。"""
    import logging
    _pop_config(monkeypatch)
    _base_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://lab.example.com")

    with caplog.at_level(logging.INFO, logger="backend.config"):
        import backend.config  # noqa: F401

    assert "lab.example.com" in caplog.text


def test_admin_token_not_set_logs_warning(monkeypatch, caplog):
    """ADMIN_TOKEN 未设置时 config 应记录 warning（管理端点禁用提示回归）。"""
    import logging
    _pop_config(monkeypatch)
    _base_env(monkeypatch)
    monkeypatch.setenv("ADMIN_TOKEN", "")  # not set

    with caplog.at_level(logging.WARNING, logger="backend.config"):
        import backend.config  # noqa: F401

    assert "ADMIN_TOKEN" in caplog.text


def test_https_registry_mirror_no_warning(monkeypatch, caplog):
    """VM_REGISTRY_MIRROR 已设置时不应产生不安全警告（H1 回归）。"""
    import logging
    from backend import config
    monkeypatch.setattr(config, "VM_REGISTRY_MIRROR", "https://registry.example.com")
    with caplog.at_level(logging.WARNING, logger="backend.config"):
        config._warn_insecure_defaults()
    assert "insecure" not in caplog.text.lower()


class TestParseExemptVmIds:
    """Tests for _parse_exempt_vm_ids() — VM_CLEANUP_EXEMPT_IDS parsing.

    Regression: systemd's EnvironmentFile does not strip inline `#` comments,
    so a .env line like `VM_CLEANUP_EXEMPT_IDS=401  # note` is loaded
    verbatim as "401  # note". The naive `.isdigit()` check silently dropped
    such entries, leaving the exemption set empty and allowing the
    auto-cleanup task to delete a protected staging VM.
    """

    def test_parses_plain_comma_separated_ids(self):
        from backend.config import _parse_exempt_vm_ids
        assert _parse_exempt_vm_ids("401,402") == frozenset({401, 402})

    def test_empty_string_yields_empty_set(self):
        from backend.config import _parse_exempt_vm_ids
        assert _parse_exempt_vm_ids("") == frozenset()

    def test_strips_inline_comment_after_value(self):
        """Regression: systemd EnvironmentFile passes inline comments through verbatim."""
        from backend.config import _parse_exempt_vm_ids
        assert _parse_exempt_vm_ids("401  # staging K3s platform VM — do not delete") == frozenset({401})

    def test_strips_inline_comment_with_multiple_ids(self):
        from backend.config import _parse_exempt_vm_ids
        assert _parse_exempt_vm_ids("401,402  # two staging VMs") == frozenset({401, 402})

    def test_logs_warning_when_input_nonempty_but_no_valid_ids(self, caplog):
        import logging
        from backend.config import _parse_exempt_vm_ids
        with caplog.at_level(logging.WARNING, logger="backend.config"):
            result = _parse_exempt_vm_ids("# only a comment, no ids")
        assert result == frozenset()
        assert "no valid VMIDs parsed" in caplog.text


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
