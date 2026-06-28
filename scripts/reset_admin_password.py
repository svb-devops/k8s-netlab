#!/usr/bin/env python3
"""
Reset an admin user's password securely.

Usage:
    python scripts/reset_admin_password.py --username smoke-admin

The new password is generated randomly and written to:
    /root/.k8s-netlab-admin-credentials  (chmod 600, root-only)

It is NEVER printed to stdout or stderr.

After running, verify with:
    python scripts/reset_admin_password.py --username smoke-admin --verify-only

Operator note: retrieve the stored credential with:
    cat /root/.k8s-netlab-admin-credentials
"""
from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.labgen.ops_env import load_ops_env

load_ops_env()

from backend.auth import AuthManager  # noqa: E402

_CRED_FILE = Path("/root/.k8s-netlab-admin-credentials")
_PASSWORD_LENGTH = 24


def _generate_password() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(_PASSWORD_LENGTH))


def _write_credential_file(username: str, password: str) -> None:
    existing: dict[str, str] = {}
    if _CRED_FILE.exists():
        for line in _CRED_FILE.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    existing[username] = password
    content = "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n"
    _CRED_FILE.write_text(content)
    os.chmod(_CRED_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0o600


def _read_credential_file(username: str) -> str | None:
    if not _CRED_FILE.exists():
        return None
    for line in _CRED_FILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == username:
                return v.strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset admin user password")
    parser.add_argument("--username", required=True, help="Admin username to reset")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify that stored credentials work (no reset)",
    )
    args = parser.parse_args()
    username = args.username

    auth = AuthManager()

    if args.verify_only:
        stored = _read_credential_file(username)
        if stored is None:
            print(f"[FAIL] No stored credential for '{username}' in {_CRED_FILE}")
            sys.exit(1)
        if auth.verify_credentials(username, stored):
            print(f"[PASS] Stored credential for '{username}' is valid")
        else:
            print(f"[FAIL] Stored credential for '{username}' is INVALID — re-run without --verify-only")
            sys.exit(1)
        return

    users = auth._load_users()
    if username not in users:
        print(f"[FAIL] User '{username}' not found in users.json")
        sys.exit(1)

    new_password = _generate_password()
    success = auth.reset_password(username, new_password)
    if not success:
        print(f"[FAIL] reset_password returned False for '{username}'")
        sys.exit(1)

    _write_credential_file(username, new_password)
    # Security: do not print password
    print(f"[PASS] Password reset for '{username}'")
    print(f"[INFO] Credential stored in: {_CRED_FILE} (chmod 600)")
    print(f"[INFO] Retrieve with: cat {_CRED_FILE}")


if __name__ == "__main__":
    main()
