"""
K8S NetLab - Proxmox API Wrapper

Provides a single function to establish a validated connection
to the Proxmox VE server using environment-based configuration.
"""

import logging
from typing import Any

from proxmoxer import ProxmoxAPI

from backend import config

logger = logging.getLogger(__name__)


def connect_proxmox() -> ProxmoxAPI:
    """
    Create and validate a connection to the Proxmox VE server.

    Prefers API Token auth (PROXMOX_TOKEN_ID / PROXMOX_TOKEN_SECRET).
    Falls back to username + password auth (PROXMOX_USER / PROXMOX_PASSWORD).

    Returns:
        ProxmoxAPI: An authenticated Proxmox API client

    Raises:
        ConnectionError: If the connection or authentication fails
    """
    host = f"{config.PROXMOX_HOST}:{config.PROXMOX_PORT}"

    try:
        if config._proxmox_auth_method == "token":
            # Token format: "user@realm!tokenname"
            parts = config.PROXMOX_TOKEN_ID.split("!")
            if len(parts) != 2:
                raise ValueError(
                    f"PROXMOX_TOKEN_ID must be 'user@realm!tokenname', "
                    f"got: {config.PROXMOX_TOKEN_ID}"
                )
            token_user, token_name = parts
            logger.info(f"Connecting to Proxmox at {host} (token auth)")
            proxmox = ProxmoxAPI(
                config.PROXMOX_HOST,
                port=config.PROXMOX_PORT,
                user=token_user,
                token_name=token_name,
                token_value=config.PROXMOX_TOKEN_SECRET,
                verify_ssl=config.PROXMOX_VERIFY_SSL,
                timeout=30,
            )
        else:
            # Password auth (legacy fallback)
            logger.info(f"Connecting to Proxmox at {host} (password auth)")
            proxmox = ProxmoxAPI(
                config.PROXMOX_HOST,
                port=config.PROXMOX_PORT,
                user=config.PROXMOX_USER,
                password=config.PROXMOX_PASSWORD,
                verify_ssl=config.PROXMOX_VERIFY_SSL,
                timeout=30,
            )
    except Exception as e:
        logger.error(f"Failed to create Proxmox client: {e}")
        raise ConnectionError(f"Cannot connect to Proxmox at {host}: {e}") from e

    # Validate connection by fetching API version
    try:
        version_info = proxmox.version.get()
        version = version_info.get("version", "unknown")
        logger.info(f"Connected to Proxmox VE {version}")
    except Exception as e:
        logger.error(f"Proxmox connection validation failed: {e}")
        raise ConnectionError(
            f"Connected to {host} but API validation failed: {e}"
        ) from e

    return proxmox
