"""
Canonical environment loader for LabGen ops scripts.

Loading order (mirrors systemd EnvironmentFile priority):
  1. /root/k8s-netlab/.env           — base project config (lower priority)
  2. /etc/labgen/home_lab_mvp.env    — production overrides (higher priority, if present)

Scripts that need production-equivalent config must call load_ops_env() BEFORE
importing any backend module, since config.py reads env vars at import time.

Usage:
    from backend.labgen.ops_env import load_ops_env
    load_ops_env()
    from backend import config  # now has production values
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DOT_ENV = _PROJECT_ROOT / ".env"
_HOME_LAB_ENV = Path("/etc/labgen/home_lab_mvp.env")


def load_ops_env(
    *,
    require_production_path: bool = False,
    _project_root: Path | None = None,
) -> dict[str, str]:
    """Load env vars in the same order as the systemd k8s-netlab.service unit.

    Returns a dict of which files were loaded:
        {"dot_env": <path or None>, "home_lab_env": <path or None>}

    Args:
        require_production_path: If True, abort with SystemExit(2) when
            home_lab_mvp.env is absent (use for ops scripts that MUST have
            the correct LABGEN_VERIFIER_CREDENTIAL_ROOT).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[ops_env] ERROR: python-dotenv not installed", file=sys.stderr)
        sys.exit(1)

    project_root = _project_root or _PROJECT_ROOT
    dot_env = project_root / ".env"

    loaded: dict[str, str | None] = {"dot_env": None, "home_lab_env": None}

    if dot_env.exists():
        load_dotenv(str(dot_env), override=False)
        loaded["dot_env"] = str(dot_env)

    if _HOME_LAB_ENV.exists():
        load_dotenv(str(_HOME_LAB_ENV), override=True)
        loaded["home_lab_env"] = str(_HOME_LAB_ENV)
    elif require_production_path:
        print(
            f"[ops_env] ABORT: require_production_path=True but "
            f"{_HOME_LAB_ENV} not found",
            file=sys.stderr,
        )
        sys.exit(2)

    return loaded  # type: ignore[return-value]


def assert_production_credential_root() -> str:
    """Abort if LABGEN_VERIFIER_CREDENTIAL_ROOT does not look like a production path.

    Returns the effective value on success.
    """
    root = os.environ.get("LABGEN_VERIFIER_CREDENTIAL_ROOT", "")
    if not root or "labgen" not in root or root.startswith("creds/"):
        print(
            f"[ops_env] ABORT: LABGEN_VERIFIER_CREDENTIAL_ROOT={root!r} "
            f"looks like default/dev path. Load home_lab_mvp.env first.",
            file=sys.stderr,
        )
        sys.exit(2)
    return root
