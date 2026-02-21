#!/usr/bin/env bash
#
# K8S NetLab - Cleanup Test VMs
#
# Deletes all test VMs (995, 996, 997, 998, 999) created during testing.
# Keeps VM 100 (template) intact.
#
# Usage:
#   ./scripts/cleanup_test_vms.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "K8S NetLab - Test VM Cleanup"
echo "=========================================="
echo ""

# Test VM IDs to clean up
TEST_VMS=(995 996 997 998 999)

echo "📊 Checking current VMs..."
python3 -c "
from dotenv import load_dotenv
load_dotenv()
from backend.vm_manager import list_vms

result = list_vms()
if result['success']:
    print('Current VMs:')
    for vm in result['data']:
        print(f\"  - VM {vm['vmid']}: {vm['name']:20} ({vm['status']})\")
"

echo ""
echo "🗑️  Cleaning up test VMs..."
echo ""

for vm_id in "${TEST_VMS[@]}"; do
    echo "Checking VM $vm_id..."

    python3 -c "
from dotenv import load_dotenv
load_dotenv()
from backend.vm_manager import delete_vm, list_vms

# Check if VM exists
result = list_vms()
if result['success']:
    vm_exists = any(vm['vmid'] == $vm_id for vm in result['data'])

    if vm_exists:
        print('  → VM $vm_id exists, deleting...')

        # Delete VM
        result = delete_vm(vm_id=$vm_id, force=True)

        if result['success']:
            print('  ✅ VM $vm_id deleted')
        else:
            print(f\"  ❌ Failed to delete VM $vm_id: {result['error']}\")
    else:
        print('  ⏭️  VM $vm_id does not exist, skipping')
"

    # Small delay between deletions
    sleep 2
done

echo ""
echo "⏳ Waiting 10 seconds for Proxmox to complete deletions..."
sleep 10

echo ""
echo "📊 Final VM list:"
python3 -c "
from dotenv import load_dotenv
load_dotenv()
from backend.vm_manager import list_vms

result = list_vms()
if result['success']:
    print('─' * 60)
    for vm in result['data']:
        status_icon = '✅' if vm['status'] == 'running' else '⏹️ '
        print(f\"  {status_icon} VM {vm['vmid']}: {vm['name']:20} ({vm['status']})\")
    print('─' * 60)

    # Check if any test VMs remain
    test_vms = [vm for vm in result['data'] if vm['vmid'] in [995, 996, 997, 998, 999]]
    if test_vms:
        print('')
        print('⚠️  Some test VMs still exist. Manual cleanup may be required.')
    else:
        print('')
        print('✅ All test VMs cleaned up successfully!')
"

echo ""
echo "=========================================="
echo "Cleanup complete!"
echo "=========================================="
