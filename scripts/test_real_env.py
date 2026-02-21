#!/usr/bin/env python3
"""
K8S NetLab - Real Environment Integration Test

Tests the full VM lifecycle against a real Proxmox server:
  1. Load .env configuration
  2. Test Proxmox connection
  3. Create VM 999 from template 100
  4. Wait 30 seconds
  5. Delete VM 999
  6. Display SmartLogger report paths

Usage:
    # First, copy and configure your .env file:
    cp .env.example .env
    # Edit .env with real Proxmox credentials

    # Run from project root:
    python scripts/test_real_env.py

WARNING: This script creates and deletes a REAL VM (ID=999) on your Proxmox server.
         Make sure VM ID 999 is not in use and template ID 100 exists.
"""

import sys
import time
from pathlib import Path

# Ensure project root is in Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- Step 0: Load .env file ---
print("=" * 60)
print("K8S NetLab - Real Environment Test")
print("=" * 60)

from dotenv import load_dotenv

env_path = PROJECT_ROOT / ".env"
if not env_path.exists():
    print(f"\n[ERROR] .env file not found at: {env_path}")
    print("Please run: cp .env.example .env")
    print("Then edit .env with your Proxmox credentials.")
    sys.exit(1)

load_dotenv(env_path)
print(f"\n[OK] Loaded .env from: {env_path}")

# Now import project modules (they read env vars at import time)
from backend.proxmox_api import connect_proxmox
from backend.vm_manager import create_vm, delete_vm, list_vms
from backend import config

TEST_VM_ID = 999
TEMPLATE_ID = 100
WAIT_SECONDS = 30

print(f"\n--- Configuration ---")
print(f"  Proxmox Host : {config.PROXMOX_HOST}:{config.PROXMOX_PORT}")
print(f"  Proxmox User : {config.PROXMOX_USER}")
print(f"  Proxmox Node : {config.PROXMOX_NODE}")
print(f"  VM Cores     : {config.VM_CORES}")
print(f"  VM Memory    : {config.VM_MEMORY_MB} MB")
print(f"  Test VM ID   : {TEST_VM_ID}")
print(f"  Template ID  : {TEMPLATE_ID}")
print(f"  Wait Time    : {WAIT_SECONDS}s")

reports = []


def run_step(step_num: int, description: str, func, *args, **kwargs):
    """
    Execute a test step with consistent formatting and error capture.

    Args:
        step_num: Step number for display
        description: Human-readable step description
        func: Function to call
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        The function result, or None on failure
    """
    print(f"\n{'=' * 60}")
    print(f"Step {step_num}: {description}")
    print(f"{'=' * 60}")

    try:
        result = func(*args, **kwargs)
        print(f"  Result: {result}")
        return result
    except Exception as e:
        print(f"  [FAILED] {type(e).__name__}: {e}")
        return None


# --- Step 1: Test Proxmox Connection ---
proxmox = run_step(1, "Test Proxmox Connection", connect_proxmox)
if proxmox is None:
    print("\n[FATAL] Cannot connect to Proxmox. Check .env credentials.")
    sys.exit(1)
print("  [OK] Proxmox connection established")

# --- Step 2: List existing VMs ---
list_result = run_step(2, "List Existing VMs", list_vms)
if list_result and list_result["success"]:
    vms = list_result["data"]
    print(f"  [OK] Found {len(vms)} VMs:")
    for vm in vms:
        print(f"       - {vm.get('vmid', '?')}: {vm.get('name', '?')} ({vm.get('status', '?')})")

    # Safety check: make sure test VM ID is not already in use
    existing_ids = [vm.get("vmid") for vm in vms]
    if TEST_VM_ID in existing_ids:
        print(f"\n  [WARNING] VM {TEST_VM_ID} already exists!")
        print(f"  Attempting to delete it first...")
        cleanup = delete_vm(TEST_VM_ID, force=True)
        if not cleanup["success"]:
            print(f"  [FATAL] Cannot clean up existing VM {TEST_VM_ID}: {cleanup['error']}")
            sys.exit(1)
        print(f"  [OK] Existing VM {TEST_VM_ID} cleaned up")
        time.sleep(5)

# --- Step 3: Create VM ---
create_result = run_step(3, f"Create VM {TEST_VM_ID} from Template {TEMPLATE_ID}",
                         create_vm, TEST_VM_ID, TEMPLATE_ID)
if create_result and create_result["success"]:
    print(f"  [OK] VM {TEST_VM_ID} created successfully")
else:
    error = create_result["error"] if create_result else "Unknown error"
    print(f"  [FAILED] VM creation failed: {error}")
    print("\n  Common causes:")
    print(f"    - Template {TEMPLATE_ID} does not exist")
    print(f"    - VM ID {TEST_VM_ID} is already in use")
    print(f"    - Insufficient resources on node '{config.PROXMOX_NODE}'")
    sys.exit(1)

# --- Step 4: Wait ---
print(f"\n{'=' * 60}")
print(f"Step 4: Waiting {WAIT_SECONDS} seconds...")
print(f"{'=' * 60}")
for i in range(WAIT_SECONDS, 0, -5):
    print(f"  {i} seconds remaining...")
    time.sleep(min(5, i))
print("  [OK] Wait complete")

# --- Step 5: Delete VM ---
delete_result = run_step(5, f"Delete VM {TEST_VM_ID}", delete_vm, TEST_VM_ID, force=True)
if delete_result and delete_result["success"]:
    print(f"  [OK] VM {TEST_VM_ID} deleted successfully")
else:
    error = delete_result["error"] if delete_result else "Unknown error"
    print(f"  [WARNING] VM deletion issue: {error}")
    print(f"  You may need to manually delete VM {TEST_VM_ID} from Proxmox.")

# --- Step 6: Show Report Paths ---
print(f"\n{'=' * 60}")
print("Step 6: SmartLogger Reports")
print(f"{'=' * 60}")
reports_dir = PROJECT_ROOT / "logs" / "reports"
if reports_dir.exists():
    report_files = sorted(reports_dir.glob("REPORT_*.txt"), key=lambda p: p.stat().st_mtime)
    if report_files:
        print(f"  Reports directory: {reports_dir}")
        print(f"  Found {len(report_files)} report(s):")
        for f in report_files[-5:]:
            print(f"    - {f.name}")
    else:
        print("  No report files found.")
else:
    print(f"  Reports directory not found: {reports_dir}")

# --- Summary ---
print(f"\n{'=' * 60}")
print("Test Summary")
print(f"{'=' * 60}")
print(f"  Connection : {'PASS' if proxmox else 'FAIL'}")
print(f"  List VMs   : {'PASS' if list_result and list_result['success'] else 'FAIL'}")
print(f"  Create VM  : {'PASS' if create_result and create_result['success'] else 'FAIL'}")
print(f"  Delete VM  : {'PASS' if delete_result and delete_result['success'] else 'FAIL'}")
print(f"{'=' * 60}")

all_passed = all([
    proxmox,
    list_result and list_result["success"],
    create_result and create_result["success"],
    delete_result and delete_result["success"],
])
if all_passed:
    print("\nAll tests PASSED! Your environment is ready for K8S NetLab.")
else:
    print("\nSome tests FAILED. Check the output above and SmartLogger reports.")

sys.exit(0 if all_passed else 1)
