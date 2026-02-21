"""
K8S NetLab - Proxmox API Wrapper

Provides a single function to establish a validated connection
to the Proxmox VE server using environment-based configuration.
"""

import logging
from typing import Dict, Any

from proxmoxer import ProxmoxAPI

from backend import config

logger = logging.getLogger(__name__)


def connect_proxmox() -> ProxmoxAPI:
    """
    Create and validate a connection to the Proxmox VE server.

    Uses configuration from backend.config (environment variables).
    Tests the connection by fetching the API version before returning.

    Returns:
        ProxmoxAPI: An authenticated Proxmox API client

    Raises:
        ConnectionError: If the connection or authentication fails
        RuntimeError: If the Proxmox server is unreachable
    """
    host = f"{config.PROXMOX_HOST}:{config.PROXMOX_PORT}"
    logger.info(f"Connecting to Proxmox at {config.PROXMOX_HOST}:{config.PROXMOX_PORT}")

    try:
        proxmox = ProxmoxAPI(
            config.PROXMOX_HOST,
            port=config.PROXMOX_PORT,
            user=config.PROXMOX_USER,
            password=config.PROXMOX_PASSWORD,
            verify_ssl=config.PROXMOX_VERIFY_SSL,
            timeout=30,  # Increase from default 5s to 30s for resource configuration
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


def get_node_status() -> Dict[str, Any]:
    """
    Get the status of the configured Proxmox node.

    Returns:
        dict: {'success': bool, 'data': dict or None, 'error': str or None}
    """
    try:
        proxmox = connect_proxmox()
        status = proxmox.nodes(config.PROXMOX_NODE).status.get()
        logger.info(f"Node '{config.PROXMOX_NODE}' status retrieved")
        return {"success": True, "data": status, "error": None}
    except ConnectionError as e:
        logger.error(f"Connection failed: {e}")
        return {"success": False, "data": None, "error": str(e)}
    except Exception as e:
        logger.critical(f"Unexpected error getting node status: {e}")
        return {"success": False, "data": None, "error": str(e)}
