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
PROXMOX_NODE: str = os.getenv("PROXMOX_NODE", "pve")
PROXMOX_VERIFY_SSL: bool = _get_env_bool("PROXMOX_VERIFY_SSL", False)

# Token auth (recommended): PROXMOX_TOKEN_ID=user@realm!tokenname
PROXMOX_TOKEN_ID: str = os.getenv("PROXMOX_TOKEN_ID", "")
PROXMOX_TOKEN_SECRET: str = os.getenv("PROXMOX_TOKEN_SECRET", "")

# Password auth (legacy fallback): required when token vars are absent
PROXMOX_USER: str = os.getenv("PROXMOX_USER", "")
PROXMOX_PASSWORD: str = os.getenv("PROXMOX_PASSWORD", "")

# Validate: exactly one auth method must be configured
if PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET:
    _proxmox_auth_method = "token"
elif PROXMOX_USER and PROXMOX_PASSWORD:
    _proxmox_auth_method = "password"
else:
    raise RuntimeError(
        "Proxmox authentication not configured. "
        "Set PROXMOX_TOKEN_ID + PROXMOX_TOKEN_SECRET (recommended) "
        "or PROXMOX_USER + PROXMOX_PASSWORD (legacy)."
    )

# --- VM SSH Configuration ---
VM_SSH_USER: str = os.getenv("VM_SSH_USER", "root")
VM_SSH_PASSWORD: str = _get_required_env("VM_SSH_PASSWORD")

# --- VM Configuration ---
VM_TEMPLATE_ID: int = _get_env_int("VM_TEMPLATE_ID", 9000)
VM_CORES: int = _get_env_int("VM_CORES", 2)
VM_MEMORY_MB: int = _get_env_int("VM_MEMORY_MB", 4096)
VM_SESSION_TIMEOUT_MIN: int = _get_env_int("VM_SESSION_TIMEOUT_MIN", 30)

# --- Application Configuration ---
APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT: int = _get_env_int("APP_PORT", 8000)
APP_DEBUG: bool = _get_env_bool("APP_DEBUG", False)
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- CORS Configuration ---
# Comma-separated list of allowed origins for cross-origin requests.
# Leave empty (default) to block all cross-origin requests.
# Example: ALLOWED_ORIGINS=https://lab.example.com,https://admin.example.com
_origins_raw = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list = [o.strip() for o in _origins_raw.split(",") if o.strip()]

if ALLOWED_ORIGINS:
    logger.info(f"CORS allowed origins: {ALLOWED_ORIGINS}")
else:
    logger.warning("CORS: ALLOWED_ORIGINS not set — all cross-origin requests will be blocked")

# --- Network Isolation Configuration ---
VM_NETWORK: str = os.getenv("VM_NETWORK", "172.16.100.0/24")
VM_GATEWAY: str = os.getenv("VM_GATEWAY", "172.16.100.1")
VM_BRIDGE: str = os.getenv("VM_BRIDGE", "vmbr1")
VM_IP_START: int = _get_env_int("VM_IP_START", 10)
VM_IP_END: int = _get_env_int("VM_IP_END", 254)

# --- Admin API Configuration ---
# Static token for the admin observability endpoint (X-Admin-Token header).
# If not set, the admin endpoint returns 503 rather than exposing a weak default.
ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")
if not ADMIN_TOKEN:
    logger.warning("ADMIN_TOKEN not set — admin API (/api/admin/status) will be disabled")

# Comma-separated list of usernames that have admin privileges.
# Admins are shown an admin badge in the UI.
# Example: ADMIN_USERNAMES=alice,bob
_admin_usernames_raw = os.getenv("ADMIN_USERNAMES", "")
ADMIN_USERNAMES: set = {u.strip() for u in _admin_usernames_raw.split(",") if u.strip()}

# --- VM Quota Configuration ---
# Maximum number of VMs a single user can own simultaneously.
# Default 1 (one VM per user). Increase for instructors/admins.
MAX_VMS_PER_USER: int = _get_env_int("MAX_VMS_PER_USER", 1)

# Maximum total VMs tracked system-wide (excludes the template).
# Recommended: number of students + 2 spares.
MAX_TOTAL_VMS: int = _get_env_int("MAX_TOTAL_VMS", 12)

logger.info(
    f"VM quota: per_user={MAX_VMS_PER_USER}, system_total={MAX_TOTAL_VMS}"
)

logger.info("Configuration loaded successfully")
