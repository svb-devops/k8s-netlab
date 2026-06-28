#!/usr/bin/env python3
"""
Provision verifier credentials for a staging VM.

Usage:
    python scripts/provision_verifier_credentials.py --vm-id 299

Requires:
    - /etc/labgen/home_lab_mvp.env (sets LABGEN_VERIFIER_CREDENTIAL_ROOT)
    - /etc/labgen/home_lab_mvp.kubeconfig (platform K3s kubeconfig, chmod 600)
    - VM must be running with K3s accessible from the Proxmox host

What it does:
    1. Loads env in production order (.env → home_lab_mvp.env)
    2. Verifies production credential root is set correctly
    3. Calls initialize_verifier_for_vm_host_side() with explicit VerifierCredentialStore
    4. Verifies files were written with correct permissions
    5. Exits 0 on success, 1 on failure

Security:
    - Never prints kubeconfig content or tokens
    - Aborts if credential root looks like a dev/default path

Operator runbook:
    After running, verify with:
        ls -la /var/lib/labgen-staging/verifier-credentials/<vm_id>/
    Then test a lab session to confirm end-to-end.
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.labgen.ops_env import assert_production_credential_root, load_ops_env

loaded = load_ops_env(require_production_path=True)
print(f"[env] dot_env={loaded['dot_env']}")
print(f"[env] home_lab_env={loaded['home_lab_env']}")

cred_root = assert_production_credential_root()
print(f"[env] LABGEN_VERIFIER_CREDENTIAL_ROOT={cred_root}")

from backend.labgen.verifier_credentials import VerifierCredentialStore
from backend.vm_manager import initialize_verifier_for_vm_host_side


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision verifier credentials for a staging VM")
    parser.add_argument("--vm-id", type=int, required=True, help="Staging VM ID (e.g. 299)")
    parser.add_argument(
        "--kubeconfig",
        default="/etc/labgen/home_lab_mvp.kubeconfig",
        help="Platform K3s kubeconfig path (default: /etc/labgen/home_lab_mvp.kubeconfig)",
    )
    args = parser.parse_args()

    vm_id = args.vm_id
    kubeconfig_path = args.kubeconfig

    if not Path(kubeconfig_path).exists():
        print(f"[ABORT] Platform kubeconfig not found: {kubeconfig_path}", file=sys.stderr)
        sys.exit(1)

    store = VerifierCredentialStore(cred_root)
    print(f"[check] VerifierCredentialStore base: {store._base}")
    print(f"[check] Target credential path: {store._base}/{vm_id}/")

    if store.exists(str(vm_id)):
        print(f"[info] Credentials already exist for VM {vm_id} — reprovisioning (idempotent)")

    print(f"[start] Provisioning verifier credentials for VM {vm_id}...")
    result = initialize_verifier_for_vm_host_side(vm_id, kubeconfig_path, store=store)

    if not result["success"]:
        print(f"[FAIL] Provisioning failed: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"[pass] Provisioning succeeded: generation={result['data']['credential_generation']}")

    cred_dir = store._base / str(vm_id)
    for p in [cred_dir, cred_dir / "kubeconfig.yaml", cred_dir / "metadata.json"]:
        if not p.exists():
            print(f"[FAIL] Expected path not found: {p}", file=sys.stderr)
            sys.exit(1)
        mode = oct(stat.S_IMODE(p.stat().st_mode))
        print(f"[ok] {p} mode={mode}")

    if not store.exists(str(vm_id)):
        print("[FAIL] store.exists() returned False after provisioning!", file=sys.stderr)
        sys.exit(1)

    print(f"[PASS] VM {vm_id} verifier credentials ready at: {cred_dir}")


if __name__ == "__main__":
    main()
