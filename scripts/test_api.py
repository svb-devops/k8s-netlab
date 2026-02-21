#!/usr/bin/env python3
"""
K8S NetLab - API Test Script

Tests the FastAPI endpoints without starting a full server.
Uses FastAPI's TestClient for fast synchronous testing.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from fastapi.testclient import TestClient
from backend.main import app

# Create test client
client = TestClient(app)

print("=" * 70)
print("K8S NetLab - API Test")
print("=" * 70)
print("")

# Test 1: Root endpoint
print("Test 1: GET /")
print("-" * 70)
response = client.get("/")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
print("")

# Test 2: API info
print("Test 2: GET /api")
print("-" * 70)
response = client.get("/api")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
print("")

# Test 3: Health check
print("Test 3: GET /api/health")
print("-" * 70)
response = client.get("/api/health")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
print("")

# Test 4: List VMs
print("Test 4: GET /api/vms")
print("-" * 70)
response = client.get("/api/vms")
print(f"Status: {response.status_code}")
data = response.json()
if data['success']:
    print(f"Success: {len(data['data'])} VMs found")
    for vm in data['data']:
        print(f"  - VM {vm['vmid']}: {vm['name']} ({vm['status']})")
else:
    print(f"Error: {data['error']}")
print("")

# Test 5: Get VM status (VM 100)
print("Test 5: GET /api/vms/100/status")
print("-" * 70)
response = client.get("/api/vms/100/status")
print(f"Status: {response.status_code}")
data = response.json()
if data['success']:
    print("VM Status:")
    for key, value in data['data'].items():
        print(f"  {key}: {value}")
else:
    print(f"Error: {data['error']}")
print("")

# Test 6: Create VM (with auto-assigned ID)
print("Test 6: POST /api/vms/create (auto-assigned ID)")
print("-" * 70)
response = client.post("/api/vms/create", json={"template_id": 100})
print(f"Status: {response.status_code}")
data = response.json()
if data['success']:
    print("VM Created:")
    print(f"  VM ID: {data['data']['vm_id']}")
    print(f"  Name: {data['data']['name']}")
    print(f"  Cores: {data['data']['cores']}")
    print(f"  Memory: {data['data']['memory_mb']} MB")
    created_vm_id = data['data']['vm_id']
    print(f"  Status: Created successfully!")
else:
    print(f"Error: {data['error']}")
    created_vm_id = None
print("")

# Test 7: Delete created VM (if creation succeeded)
if created_vm_id:
    print(f"Test 7: DELETE /api/vms/{created_vm_id}")
    print("-" * 70)

    # Wait a bit for VM to be fully created
    import time
    print("Waiting 15 seconds for VM to settle...")
    time.sleep(15)

    response = client.delete(f"/api/vms/{created_vm_id}?force=true")
    print(f"Status: {response.status_code}")
    data = response.json()
    if data['success']:
        print(f"VM {created_vm_id} deleted successfully")
        print(f"  Previous status: {data['data']['previous_status']}")
    else:
        print(f"Error: {data['error']}")
    print("")

print("=" * 70)
print("✅ API Tests Complete!")
print("=" * 70)
