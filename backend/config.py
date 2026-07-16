"""
K8S NetLab - Application Configuration

Loads all configuration from environment variables.
No hardcoded secrets. Fails fast if required variables are missing.
"""

import logging
import os

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


def _parse_exempt_vm_ids(raw: str) -> frozenset:
    """
    Parse VM_CLEANUP_EXEMPT_IDS from a comma-separated string.

    systemd's EnvironmentFile does NOT strip inline `#` comments (unlike shell
    `.env` parsing) — `VALUE=401  # comment` is loaded verbatim as
    "401  # comment", silently breaking naive `.isdigit()` checks. Each token
    is stripped of any `#...` suffix before validation to guard against this.

    Args:
        raw: Raw comma-separated VMID string, e.g. "401,402" or "401  # note"

    Returns:
        frozenset[int]: Parsed VMIDs. Logs a warning if any comma-separated
        part fails to parse as a VMID (likely misconfiguration), including
        the case where every part fails.
    """
    parts = [p.split("#", 1)[0].strip() for p in raw.split(",")]
    parts = [p for p in parts if p]
    rejected = [p for p in parts if not p.isdigit()]
    ids = frozenset(int(p) for p in parts if p.isdigit())
    if rejected:
        logger.warning(
            f"VM_CLEANUP_EXEMPT_IDS contains unparseable entries {rejected!r} "
            f"(raw value: {raw!r}) — those entries will NOT be exempted"
        )
    return ids


# VMIDs that auto-cleanup must never delete (platform/staging VMs)
# Comma-separated integers, e.g. "401,402"
VM_CLEANUP_EXEMPT_IDS: frozenset = _parse_exempt_vm_ids(os.getenv("VM_CLEANUP_EXEMPT_IDS", ""))

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
# Registry mirror running on Proxmox host (pull-through cache for docker.io)
# Defaults to http://<VM_GATEWAY>:5000; set to empty string to disable
VM_REGISTRY_MIRROR: str = os.getenv("VM_REGISTRY_MIRROR", "")
# Custom push-capable registry for non-docker.io images (us-docker.pkg.dev, registry.k8s.io)
# Defaults to http://<VM_GATEWAY>:5001
VM_REGISTRY_MIRROR_CUSTOM: str = os.getenv("VM_REGISTRY_MIRROR_CUSTOM", "")

# --- Admin API Configuration ---
# Static token for the admin observability endpoint (X-Admin-Token header).
# If not set, the admin endpoint returns 503 rather than exposing a weak default.
ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")
if not ADMIN_TOKEN:
    logger.warning("ADMIN_TOKEN not set — admin API (/api/admin/status) will be disabled")
elif len(ADMIN_TOKEN) < 32:
    raise RuntimeError(
        f"ADMIN_TOKEN must be at least 32 characters for brute-force resistance "
        f"(current length: {len(ADMIN_TOKEN)})."
    )

# Comma-separated list of usernames that have admin privileges.
# Admins are shown an admin badge in the UI.
# Example: ADMIN_USERNAMES=alice,bob
_admin_usernames_raw = os.getenv("ADMIN_USERNAMES", "")
ADMIN_USERNAMES: set = {u.strip() for u in _admin_usernames_raw.split(",") if u.strip()}

# --- Session Cookie Configuration ---
# Set to True in production (HTTPS). False only for local HTTP dev.
# Default True — production runs behind HTTPS.
SESSION_COOKIE_SECURE: bool = _get_env_bool("SESSION_COOKIE_SECURE", True)

# --- VM Quota Configuration ---
# Maximum number of VMs a single user can own simultaneously.
# Default 1 (one VM per user). Increase for instructors/admins.
MAX_VMS_PER_USER: int = _get_env_int("MAX_VMS_PER_USER", 1)

# Maximum total VMs tracked system-wide (excludes the template).
# Recommended: number of students + 2 spares.
MAX_TOTAL_VMS: int = _get_env_int("MAX_TOTAL_VMS", 12)

# --- VM ID Auto-Assignment Range ---
# Range scanned when auto-assigning a VM ID (client did not specify one).
# Must not overlap with VM_TEMPLATE_ID or other projects' VMID ranges.
VM_ID_MIN: int = _get_env_int("VM_ID_MIN", 500)
VM_ID_MAX: int = _get_env_int("VM_ID_MAX", 599)

# --- Proxmox Pool ---
# All project VMs are placed in this pool for permission scoping.
PROXMOX_POOL: str = os.getenv("PROXMOX_POOL", "k8s-netlab")

logger.info(
    f"VM quota: per_user={MAX_VMS_PER_USER}, system_total={MAX_TOTAL_VMS}"
)

# --- Startup cross-validation ---
if VM_ID_MIN <= VM_TEMPLATE_ID <= VM_ID_MAX:
    raise RuntimeError(
        f"VM_TEMPLATE_ID ({VM_TEMPLATE_ID}) must not overlap with the VM auto-assignment range "
        f"({VM_ID_MIN}–{VM_ID_MAX}). Adjust VM_ID_MIN/VM_ID_MAX or VM_TEMPLATE_ID."
    )
if MAX_VMS_PER_USER > MAX_TOTAL_VMS:
    raise RuntimeError(
        f"MAX_VMS_PER_USER ({MAX_VMS_PER_USER}) cannot exceed MAX_TOTAL_VMS ({MAX_TOTAL_VMS})."
    )

# --- Directus CMS Configuration ---
# URL of the Directus instance. Leave empty to disable Directus auth.
DIRECTUS_URL: str = os.getenv("DIRECTUS_URL", "")
# Token verification cache TTL in seconds (avoids per-request roundtrips to Directus).
DIRECTUS_TOKEN_CACHE_TTL: int = _get_env_int("DIRECTUS_TOKEN_CACHE_TTL", 60)

if DIRECTUS_URL:
    logger.info(f"Directus integration enabled: {DIRECTUS_URL}")
else:
    logger.info("Directus integration disabled (DIRECTUS_URL not set)")

# --- Email Verification Configuration ---
# Resend API key for sending registration verification codes. Leave empty to
# disable email verification (registration proceeds unverified, as before).
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL: str = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

if RESEND_API_KEY:
    logger.info("Email verification enabled (RESEND_API_KEY set)")
else:
    logger.info("Email verification disabled (RESEND_API_KEY not set)")

# --- AI Tutor Configuration ---
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
# Maximum turns to keep in per-session chat history (older turns are pruned)
AI_TUTOR_MAX_TURNS: int = _get_env_int("AI_TUTOR_MAX_TURNS", 20)

if not DEEPSEEK_API_KEY:
    logger.warning("DEEPSEEK_API_KEY not set — AI tutor (/api/ai/chat) will be unavailable")

# --- LabGen Runtime Mode ---
# Controls which namespace lifecycle adapter is used and whether production safety checks apply.
# LABGEN_RUNTIME_MODE: test | dev | demo | production
#   - test/dev/demo: stub adapter allowed (no real K8s ops)
#   - production: k8s adapter required; stub adapter is a blocking error (fail closed)
# LABGEN_NAMESPACE_ADAPTER: stub | k8s
#   - stub: StubNamespaceLifecycleAdapter (no real K8s, for test/dev/demo only)
#   - k8s: K3sNamespaceLifecycleAdapter (requires LABGEN_K8S_PLATFORM_KUBECONFIG_PATH)
# LABGEN_K8S_PLATFORM_KUBECONFIG_PATH: path to the platform kubeconfig used for namespace management.
#   Required when LABGEN_NAMESPACE_ADAPTER=k8s and LABGEN_RUNTIME_MODE=production.
#   Distinct from verifier kubeconfig (which is per-VM).
LABGEN_RUNTIME_MODE: str = os.getenv("LABGEN_RUNTIME_MODE", "dev")
LABGEN_NAMESPACE_ADAPTER: str = os.getenv("LABGEN_NAMESPACE_ADAPTER", "stub")
LABGEN_K8S_PLATFORM_KUBECONFIG_PATH: str = os.getenv("LABGEN_K8S_PLATFORM_KUBECONFIG_PATH", "")

# Whether to use in-cluster Kubernetes config (for cloud/EKS/ACK environments).
# Mutually exclusive with LABGEN_K8S_PLATFORM_KUBECONFIG_PATH.
LABGEN_K8S_IN_CLUSTER: bool = _get_env_bool("LABGEN_K8S_IN_CLUSTER", False)

# Optional kubeconfig context to use (leave empty for default context).
LABGEN_K8S_CONTEXT: str = os.getenv("LABGEN_K8S_CONTEXT", "")

# Kubernetes API call timeout in seconds for namespace lifecycle operations.
LABGEN_K8S_API_TIMEOUT_SECONDS: int = _get_env_int("LABGEN_K8S_API_TIMEOUT_SECONDS", 10)
if LABGEN_K8S_API_TIMEOUT_SECONDS < 1:
    raise RuntimeError("LABGEN_K8S_API_TIMEOUT_SECONDS must be >= 1")

# Comma-separated allowed namespace prefixes. Namespaces not starting with one
# of these prefixes are rejected before any K8s API call.
# Default "lab-" matches the existing lab-<uuid> naming convention.
LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES: str = os.getenv(
    "LABGEN_K8S_NAMESPACE_ALLOWED_PREFIXES", "lab-"
)

# Verifier service account, role, and rolebinding names.
# Must be valid Kubernetes resource names (DNS subdomain).
LABGEN_K8S_VERIFIER_SA_NAME: str = os.getenv("LABGEN_K8S_VERIFIER_SA_NAME", "lab-verifier")
LABGEN_K8S_VERIFIER_SA_NAMESPACE: str = os.getenv("LABGEN_K8S_VERIFIER_SA_NAMESPACE", "kube-system")
LABGEN_K8S_VERIFIER_ROLE_NAME: str = os.getenv(
    "LABGEN_K8S_VERIFIER_ROLE_NAME", "lab-verifier-namespace-readonly"
)
LABGEN_K8S_VERIFIER_ROLEBINDING_NAME: str = os.getenv(
    "LABGEN_K8S_VERIFIER_ROLEBINDING_NAME", "lab-verifier-readonly"
)

# Root directory for per-VM verifier credential files.
# In production this must be an absolute path outside the application directory
# (e.g. /var/lib/labgen/verifier-credentials).
# Default "creds/vm_creds" is relative to CWD — only acceptable for dev/test.
LABGEN_VERIFIER_CREDENTIAL_ROOT: str = (
    os.getenv("LABGEN_VERIFIER_CREDENTIAL_ROOT") or "creds/vm_creds"
)

# Lab session TTL in minutes.  Sessions active beyond this threshold are eligible
# for expiry by VMExpiryService (admin-triggered or cron).
# Default 30 minutes; must be a positive integer in production.
LABGEN_LAB_SESSION_TTL_MINUTES: int = _get_env_int("LABGEN_LAB_SESSION_TTL_MINUTES", 30)
if LABGEN_LAB_SESSION_TTL_MINUTES < 1:
    raise RuntimeError(
        f"LABGEN_LAB_SESSION_TTL_MINUTES must be ≥ 1, got {LABGEN_LAB_SESSION_TTL_MINUTES}"
    )

# Namespace deletion retry config for LabSessionService._do_cleanup().
# K3s namespace deletion is async: the namespace enters Terminating before being gone.
# home_lab_mvp requires ≥30s total (15×2s) to handle the async window; stub adapters
# return True immediately so the larger defaults are harmless for tests.
LABGEN_NS_DELETE_MAX_RETRIES: int = _get_env_int("LABGEN_NS_DELETE_MAX_RETRIES", 15)
LABGEN_NS_DELETE_POLL_INTERVAL_S: float = float(
    os.getenv("LABGEN_NS_DELETE_POLL_INTERVAL_S", "2.0")
)

# --- LabGen Linux Learner Runtime Configuration ---
# LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS: comma-separated list of lab IDs (full UUIDs)
# that are enabled for learner sessions. Empty = all Linux labs blocked (default).
# Set only the lab IDs that have passed the Linux Learner Runtime Enablement Gate.
def _parse_lab_id_set(raw: str) -> frozenset:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return frozenset(parts)


LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS: frozenset = _parse_lab_id_set(
    os.getenv("LABGEN_LINUX_LEARNER_ENABLED_LAB_IDS", "")
)

# LABGEN_ENABLED_LAB_IDS: comma-separated list of lab IDs (any domain) that
# non-admin users may create sessions for. Empty = no lab accessible to the
# general public (default — LabGen stays admin-only while under development).
# Admins (config.ADMIN_USERNAMES) always bypass this gate.
LABGEN_ENABLED_LAB_IDS: frozenset = _parse_lab_id_set(
    os.getenv("LABGEN_ENABLED_LAB_IDS", "")
)

# LABGEN_AUTO_VM_PROVISION_LAB_IDS: comma-separated lab IDs for which a user
# with no assigned VM gets one auto-created in the background (P0 Reader Path
# Repair) instead of being told to visit /app. Empty = no lab auto-provisions
# (safe default) — scoped explicitly to launched First-Wave labs only. Labs
# not in this set keep the original no_vm_assigned + "visit /app" behavior.
LABGEN_AUTO_VM_PROVISION_LAB_IDS: frozenset = _parse_lab_id_set(
    os.getenv("LABGEN_AUTO_VM_PROVISION_LAB_IDS", "")
)

# Sandbox root directory for Linux learner workspaces.
LABGEN_LINUX_SANDBOX_ROOT: str = os.getenv(
    "LABGEN_LINUX_SANDBOX_ROOT", "/tmp/labgen-linux-sandboxes"
)

# --- LabGen LLM Provider Configuration ---
# LABGEN_LLM_MODE: high-level mode switch for article-to-lab draft generation.
#   fake_only        — deterministic template-based generation (default, no LLM, no API keys)
#   live_admin_only  — calls real LLM; enforced admin-only at route level;
#                      requires LABGEN_LLM_OPENAI_* vars and LABGEN_LLM_PROVIDER_MODE=live_enabled
# Default MUST remain fake_only — live mode requires explicit opt-in.
LABGEN_LLM_MODE: str = os.getenv("LABGEN_LLM_MODE", "fake_only")

# Low-level provider boundary (used by LabDraftGenerationService / LLMProviderBoundaryService).
# Controls the provider boundary for LabGen draft generation.
# Default: fake_only — no real LLM, no API keys, no network calls.
# Changing to a live provider requires separate credential injection (not implemented here).
LABGEN_LLM_PROVIDER_MODE: str = os.getenv("LABGEN_LLM_PROVIDER_MODE", "fake_only")
LABGEN_LLM_PROVIDER_NAME: str = os.getenv("LABGEN_LLM_PROVIDER_NAME", "fake")
LABGEN_LLM_TIMEOUT_MS: int = min(_get_env_int("LABGEN_LLM_TIMEOUT_MS", 30000), 60000)
LABGEN_LLM_MAX_OUTPUT_TOKENS: int = min(_get_env_int("LABGEN_LLM_MAX_OUTPUT_TOKENS", 4096), 8192)

# OpenAI-compatible provider — only used when LABGEN_LLM_PROVIDER_MODE=live_enabled
# API key is intentionally a plain string here; never logged, never returned via API.
LABGEN_LLM_OPENAI_BASE_URL: str = os.getenv("LABGEN_LLM_OPENAI_BASE_URL", "")
LABGEN_LLM_OPENAI_MODEL: str = os.getenv("LABGEN_LLM_OPENAI_MODEL", "")
LABGEN_LLM_OPENAI_API_KEY: str = os.getenv("LABGEN_LLM_OPENAI_API_KEY", "")


def _warn_insecure_defaults() -> None:
    """Log warnings for insecure default configuration values."""
    if not VM_REGISTRY_MIRROR:
        logger.warning(
            "VM_REGISTRY_MIRROR not set — VM setup will use insecure HTTP fallback "
            f"http://{VM_GATEWAY}:5000. Set VM_REGISTRY_MIRROR to an HTTPS endpoint in production."
        )


_warn_insecure_defaults()
logger.info("Configuration loaded successfully")
