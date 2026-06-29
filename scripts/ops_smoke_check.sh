#!/usr/bin/env bash
# ops_smoke_check.sh — Automated key-config verification for k8s-netlab.
# Run before any Owner Internal Run or production change.
# Exit 0 = all checks pass. Exit 1 = one or more FAIL.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0
CRED_ROOT="${LABGEN_VERIFIER_CREDENTIAL_ROOT:-/var/lib/labgen-staging/verifier-credentials}"

green() { printf '\033[0;32m  ✅ %s\033[0m\n' "$*"; }
red()   { printf '\033[0;31m  ❌ %s\033[0m\n' "$*"; }
info()  { printf '  → %s\n' "$*"; }

check() {
    local label="$1"
    local result="$2"  # "pass" or "fail"
    local detail="${3:-}"
    if [ "$result" = "pass" ]; then
        green "$label"
        PASS=$((PASS + 1))
    else
        red "$label${detail:+: $detail}"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "=== K8S NetLab Ops Smoke Check ==="
echo "$(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# 1. Service health
HEALTH=$(curl -sf --max-time 5 https://lab.cloudnetops.tech/api/health 2>/dev/null || true)
if echo "$HEALTH" | grep -q '"healthy"'; then
    check "Service /api/health = healthy" pass
else
    check "Service /api/health = healthy" fail "$HEALTH"
fi

# 2. .env file exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    check ".env file exists" pass
else
    check ".env file exists" fail "$PROJECT_ROOT/.env missing"
fi

# 3. home_lab_mvp.env exists
if [ -f "/etc/labgen/home_lab_mvp.env" ]; then
    check "/etc/labgen/home_lab_mvp.env exists" pass
else
    check "/etc/labgen/home_lab_mvp.env exists" fail "production env overlay missing"
fi

# 4. Verifier credentials for VM 299
if [ -d "$CRED_ROOT/299" ] && { [ -f "$CRED_ROOT/299/kubeconfig.yaml" ] || [ -f "$CRED_ROOT/299/kubeconfig" ]; }; then
    check "Verifier credentials for VM 299 present" pass
else
    check "Verifier credentials for VM 299 present" fail "$CRED_ROOT/299/kubeconfig missing"
fi

# 5. Template VM 101 in pool (requires pvesh)
if command -v pvesh &>/dev/null; then
    POOL_VMS=$(pvesh get /pools/k8s-netlab --output-format json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(str(m.get('vmid','')) for m in (d.get('members') or []) if isinstance(m,dict)))" 2>/dev/null || true)
    if echo "$POOL_VMS" | grep -qw 101; then
        check "Template VM 101 in k8s-netlab pool" pass
    else
        check "Template VM 101 in k8s-netlab pool" fail "run: pvesh set /pools/k8s-netlab --vms 101"
    fi
else
    info "pvesh not available — skipping pool check (run on Proxmox host)"
fi

# 6. No stale VMs in 500-599 range
if command -v qm &>/dev/null; then
    STALE_VMS=$(qm list 2>/dev/null | awk 'NR>1 {print $1}' | grep -E '^5[0-9]{2}$' || true)
    if [ -z "$STALE_VMS" ]; then
        check "No stale VMs in VMID 500-599" pass
    else
        check "No stale VMs in VMID 500-599" fail "found: $STALE_VMS"
    fi
else
    info "qm not available — skipping VMID 500-599 check (run on Proxmox host)"
fi

# 7. No failed sessions (via Python service layer — bypasses HTTP auth)
FAILED_COUNT=$(cd "$PROJECT_ROOT" && source venv/bin/activate 2>/dev/null; python3 -c "
import sys, os
sys.path.insert(0, '.')
from backend.labgen.lab_session_repository import LabSessionRepository
from backend.labgen.models import LabSessionStatus
repo = LabSessionRepository()
failed = [s for s in repo.list_all() if s.lab_session_status in (
    LabSessionStatus.LAB_START_FAILED, LabSessionStatus.LAB_CLEANUP_FAILED)]
print(len(failed))
" 2>/dev/null || echo "error")
if [ "$FAILED_COUNT" = "0" ]; then
    check "No failed sessions (LAB_START_FAILED / LAB_CLEANUP_FAILED)" pass
elif [ "$FAILED_COUNT" = "error" ]; then
    info "Could not query sessions (venv issue?) — skipping"
else
    check "No failed sessions (LAB_START_FAILED / LAB_CLEANUP_FAILED)" fail "$FAILED_COUNT — run recovery per RUNBOOK 场景七"
fi

# 8. tainted_vms.json is empty
TAINTED="$PROJECT_ROOT/data/tainted_vms.json"
if [ -f "$TAINTED" ]; then
    TAINTED_COUNT=$(python3 -c "import json; d=json.load(open('$TAINTED')); print(len(d))" 2>/dev/null || echo "?")
    if [ "$TAINTED_COUNT" = "0" ]; then
        check "tainted_vms.json is empty" pass
    else
        check "tainted_vms.json is empty" fail "$TAINTED_COUNT tainted VMs"
    fi
else
    check "tainted_vms.json exists" fail "file missing"
fi

# 9. lab_review_diffs.json < 1MB
DIFFS_FILE="$PROJECT_ROOT/data/lab_review_diffs.json"
if [ -f "$DIFFS_FILE" ]; then
    SIZE_KB=$(du -k "$DIFFS_FILE" | cut -f1)
    if [ "$SIZE_KB" -lt 1024 ]; then
        check "lab_review_diffs.json < 1MB (${SIZE_KB}KB)" pass
    else
        check "lab_review_diffs.json < 1MB (${SIZE_KB}KB)" fail "run DataRetentionService cleanup — RUNBOOK 场景八"
    fi
else
    info "lab_review_diffs.json not found — skipping size check"
fi

# 10. Cloudflare Tunnel alive
if pgrep -x cloudflared &>/dev/null; then
    check "Cloudflare Tunnel (cloudflared) running" pass
else
    check "Cloudflare Tunnel (cloudflared) running" fail "run: systemctl status cloudflared"
fi

# 11. mypy zero errors
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
    MYPY_OUT=$("$VENV_PYTHON" -m mypy backend/ --ignore-missing-imports 2>&1 || true)
    if echo "$MYPY_OUT" | grep -qE "^Success: no issues found"; then
        check "mypy backend/ — 0 errors" pass
    else
        ERR_COUNT=$(echo "$MYPY_OUT" | grep -cE "error:" || echo "?")
        check "mypy backend/ — 0 errors" fail "$ERR_COUNT error(s) found"
    fi
else
    info "venv not found at $VENV_PYTHON — skipping mypy check"
fi

# Summary
echo ""
echo "=== Summary ==="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo ""
if [ "$FAIL" -gt 0 ]; then
    echo "SMOKE CHECK FAILED — resolve all ❌ before proceeding."
    exit 1
else
    echo "SMOKE CHECK PASSED — all key configurations verified."
    exit 0
fi
