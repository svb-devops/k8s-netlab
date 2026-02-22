"""
K8S NetLab - Application Configuration

Loads all configuration from environment variables.
No hardcoded secrets. Fails fast if required variables are missing.
"""

import os
import logging

logger = logging.getLogger(__name__)


def _get_required_env(key: str) -> str:
    """
    Get a required environment variable.

    Args:
        key: Environment variable name

    Returns:
        str: The environment variable value

    Raises:
        RuntimeError: If the variable is not set
    """
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def _get_env_int(key: str, default: int) -> int:
    """
    Get an environment variable as integer with a default.

    Args:
        key: Environment variable name
        default: Default value if not set

    Returns:
        int: The parsed integer value

    Raises:
        ValueError: If the value cannot be parsed as int
    """
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {key} must be an integer, got: {raw}")


def _get_env_bool(key: str, default: bool) -> bool:
    """
    Get an environment variable as boolean with a default.

    Args:
        key: Environment variable name
        default: Default value if not set

    Returns:
        bool: The parsed boolean value
    """
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.lower() in ("true", "1", "yes")


# --- Proxmox Configuration ---
PROXMOX_HOST: str = _get_required_env("PROXMOX_HOST")
PROXMOX_PORT: int = _get_env_int("PROXMOX_PORT", 8006)
PROXMOX_USER: str = _get_required_env("PROXMOX_USER")
PROXMOX_PASSWORD: str = _get_required_env("PROXMOX_PASSWORD")
PROXMOX_VERIFY_SSL: bool = _get_env_bool("PROXMOX_VERIFY_SSL", False)
PROXMOX_NODE: str = os.getenv("PROXMOX_NODE", "pve")

# --- VM SSH Configuration ---
VM_SSH_USER: str = os.getenv("VM_SSH_USER", "k8s_lab")
VM_SSH_PASSWORD: str = _get_required_env("VM_SSH_PASSWORD")

# --- VM Configuration ---
VM_TEMPLATE_ID: int = _get_env_int("VM_TEMPLATE_ID", 100)
VM_CORES: int = _get_env_int("VM_CORES", 4)
VM_MEMORY_MB: int = _get_env_int("VM_MEMORY_MB", 8192)
VM_SESSION_TIMEOUT_MIN: int = _get_env_int("VM_SESSION_TIMEOUT_MIN", 30)

# --- Application Configuration ---
APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT: int = _get_env_int("APP_PORT", 8000)
APP_DEBUG: bool = _get_env_bool("APP_DEBUG", False)
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- Network Isolation Configuration ---
VM_NETWORK: str = os.getenv("VM_NETWORK", "172.16.100.0/24")
VM_GATEWAY: str = os.getenv("VM_GATEWAY", "172.16.100.1")
VM_BRIDGE: str = os.getenv("VM_BRIDGE", "vmbr1")
VM_IP_START: int = _get_env_int("VM_IP_START", 10)
VM_IP_END: int = _get_env_int("VM_IP_END", 254)

logger.info("Configuration loaded successfully")
