"""
Tests for backend/proxmox_api.py

All Proxmox calls are mocked - no real server needed.
"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    """Patch config values directly - avoids module caching issues."""
    from backend import config
    monkeypatch.setattr(config, "PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setattr(config, "PROXMOX_PORT", 8006)
    monkeypatch.setattr(config, "PROXMOX_TOKEN_ID", "testuser@pve!mytoken")
    monkeypatch.setattr(config, "PROXMOX_TOKEN_SECRET", "test-secret-uuid")
    monkeypatch.setattr(config, "PROXMOX_VERIFY_SSL", False)
    monkeypatch.setattr(config, "PROXMOX_NODE", "pve")
    monkeypatch.setattr(config, "_proxmox_auth_method", "token")


class TestConnectProxmox:
    """Tests for connect_proxmox()"""

    @patch("backend.proxmox_api.ProxmoxAPI")
    def test_successful_connection(self, mock_pve_cls):
        """Returns ProxmoxAPI instance on successful token-auth connection."""
        mock_instance = MagicMock()
        mock_instance.version.get.return_value = {"version": "8.1.3"}
        mock_pve_cls.return_value = mock_instance

        from backend.proxmox_api import connect_proxmox
        result = connect_proxmox()

        assert result is mock_instance
        mock_pve_cls.assert_called_once_with(
            "10.0.0.1",
            port=8006,
            user="testuser@pve",
            token_name="mytoken",
            token_value="test-secret-uuid",
            verify_ssl=False,
            timeout=30,
        )
        mock_instance.version.get.assert_called_once()

    @patch("backend.proxmox_api.ProxmoxAPI")
    def test_connection_failure_raises(self, mock_pve_cls):
        """Raises ConnectionError when Proxmox is unreachable."""
        mock_pve_cls.side_effect = Exception("Connection refused")

        from backend.proxmox_api import connect_proxmox
        with pytest.raises(ConnectionError, match="Cannot connect to Proxmox"):
            connect_proxmox()

    @patch("backend.proxmox_api.ProxmoxAPI")
    def test_connect_log_does_not_leak_token_id(self, mock_pve_cls, caplog):
        """connect_proxmox INFO 日志不得暴露 token_user 或 token_name（A1 回归）。"""
        import logging
        mock_instance = MagicMock()
        mock_instance.version.get.return_value = {"version": "8.1.3"}
        mock_pve_cls.return_value = mock_instance

        from backend.proxmox_api import connect_proxmox
        with caplog.at_level(logging.INFO, logger="backend.proxmox_api"):
            connect_proxmox()

        assert "testuser@pve" not in caplog.text, "Token user must not appear in logs"
        assert "mytoken" not in caplog.text, "Token name must not appear in logs"

    @patch("backend.proxmox_api.ProxmoxAPI")
    def test_validation_failure_raises(self, mock_pve_cls):
        """Raises ConnectionError when API validation fails."""
        mock_instance = MagicMock()
        mock_instance.version.get.side_effect = Exception("401 Unauthorized")
        mock_pve_cls.return_value = mock_instance

        from backend.proxmox_api import connect_proxmox
        with pytest.raises(ConnectionError, match="API validation failed"):
            connect_proxmox()


