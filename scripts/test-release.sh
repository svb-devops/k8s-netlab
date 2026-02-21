#!/usr/bin/env bash
# K8S NetLab v1.0 - Release Test Script
# Usage: bash scripts/test-release.sh [host] [port]
# Default: localhost 8000

set -euo pipefail

HOST="${1:-localhost}"
PORT="${2:-8000}"
BASE="http://${HOST}:${PORT}"

PASS=0
FAIL=0
SKIP=0

# ─── Helpers ──────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
info() { echo -e "\n${CYAN}▶ $1${NC}"; }
skip() { echo -e "  ${YELLOW}⊘${NC} $1 (skipped)"; SKIP=$((SKIP + 1)); }

# GET request: returns HTTP status code
http_status() {
    curl -s -o /dev/null -w "%{http_code}" "$1"
}

# GET request: returns body
http_body() {
    curl -s "$1"
}

# Check JSON field exists and has value
json_has() {
    local body="$1" field="$2"
    echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('$field'); sys.exit(0 if v is not None else 1)" 2>/dev/null
}

json_count() {
    local body="$1" field="$2"
    echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('$field', [])))" 2>/dev/null
}

json_value() {
    local body="$1" field="$2"
    echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$field',''))" 2>/dev/null
}

# ─── Tests ────────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════"
echo "  K8S NetLab v1.0 Release Test"
echo "  Target: ${BASE}"
echo "════════════════════════════════════════"

# ── 1. Server Reachability ─────────────────────────────────────────────────

info "1. Server Reachability"

status=$(http_status "${BASE}/")
if [ "$status" = "200" ]; then
    ok "GET / → ${status}"
else
    fail "GET / → ${status} (expected 200)"
fi

status=$(http_status "${BASE}/login.html")
if [ "$status" = "200" ]; then
    ok "GET /login.html → ${status}"
else
    fail "GET /login.html → ${status} (expected 200)"
fi

status=$(http_status "${BASE}/api")
if [ "$status" = "200" ]; then
    ok "GET /api → ${status}"
else
    fail "GET /api → ${status} (expected 200)"
fi

# ── 2. Health Check ────────────────────────────────────────────────────────

info "2. Health Check"

body=$(http_body "${BASE}/api/health")
status=$(http_status "${BASE}/api/health")

if [ "$status" = "200" ]; then
    ok "GET /api/health → 200"
else
    fail "GET /api/health → ${status} (expected 200)"
fi

health_status=$(json_value "$body" "status")
if [ "$health_status" = "healthy" ]; then
    ok "status = \"healthy\""
else
    fail "status = \"${health_status}\" (expected \"healthy\")"
fi

proxmox_connected=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('proxmox',{}).get('connected',''))" 2>/dev/null)
if [ "$proxmox_connected" = "True" ]; then
    ok "Proxmox connected = true"
else
    skip "Proxmox connected = ${proxmox_connected} (Proxmox may be unreachable)"
fi

# ── 3. Experiment List API ─────────────────────────────────────────────────

info "3. Experiment List API"

body=$(http_body "${BASE}/api/experiments")
status=$(http_status "${BASE}/api/experiments")

if [ "$status" = "200" ]; then
    ok "GET /api/experiments → 200"
else
    fail "GET /api/experiments → ${status} (expected 200)"
fi

count=$(json_count "$body" "experiments")
if [ "$count" = "11" ]; then
    ok "Experiment count = 11"
else
    fail "Experiment count = ${count} (expected 11)"
fi

# Check required fields in first experiment
first=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); e=d['experiments'][0]; print(json.dumps(e))" 2>/dev/null)
for field in id title difficulty duration phase; do
    val=$(echo "$first" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$field','MISSING'))" 2>/dev/null)
    if [ "$val" != "MISSING" ] && [ -n "$val" ]; then
        ok "List field '$field' present"
    else
        fail "List field '$field' missing"
    fi
done

# ── 4. Experiment Content API ──────────────────────────────────────────────

info "4. Experiment Content API"

for exp_id in 01 06 11; do
    body=$(http_body "${BASE}/api/experiments/${exp_id}")
    status=$(http_status "${BASE}/api/experiments/${exp_id}")

    if [ "$status" = "200" ]; then
        ok "GET /api/experiments/${exp_id} → 200"
    else
        fail "GET /api/experiments/${exp_id} → ${status} (expected 200)"
        continue
    fi

    content_len=$(json_value "$body" "content" | wc -c)
    if [ "$content_len" -gt 500 ]; then
        ok "Experiment ${exp_id} content length = ${content_len} chars"
    else
        fail "Experiment ${exp_id} content too short (${content_len} chars)"
    fi

    # Check 'Step N' headings in content
    step_count=$(json_value "$body" "content" | grep -c "^### Step [0-9]" || true)
    if [ "$step_count" -gt 0 ]; then
        ok "Experiment ${exp_id} has ${step_count} step headings"
    else
        fail "Experiment ${exp_id} has no '### Step N' headings"
    fi
done

# ── 5. 404 Handling ────────────────────────────────────────────────────────

info "5. Error Handling"

status=$(http_status "${BASE}/api/experiments/99")
if [ "$status" = "404" ]; then
    ok "GET /api/experiments/99 → 404 (correct)"
else
    fail "GET /api/experiments/99 → ${status} (expected 404)"
fi

status=$(http_status "${BASE}/api/experiments/00")
if [ "$status" = "404" ]; then
    ok "GET /api/experiments/00 → 404 (correct)"
else
    fail "GET /api/experiments/00 → ${status} (expected 404)"
fi

# ── 6. Static Files ────────────────────────────────────────────────────────

info "6. Static Files"

for f in api.js app.js docs.js terminal.js auth.js; do
    status=$(http_status "${BASE}/js/${f}")
    if [ "$status" = "200" ]; then
        ok "GET /js/${f} → 200"
    else
        fail "GET /js/${f} → ${status} (expected 200)"
    fi
done

# ── 7. Experiment Files on Disk ────────────────────────────────────────────

info "7. Experiment Files on Disk"

EXP_DIR="/root/k8s-netlab/docs/experiments"

declare -A EXPECTED_STEPS=(
    ["01"]=7 ["02"]=9 ["03"]=10 ["04"]=10 ["05"]=7
    ["06"]=7 ["07"]=8 ["08"]=8 ["09"]=7 ["10"]=6 ["11"]=7
)

all_ok=true
for id in $(seq -w 1 11); do
    # find the file
    files=("${EXP_DIR}/${id}-"*.md)
    if [ -f "${files[0]}" ]; then
        f="${files[0]}"
        steps=$(grep -c "^### Step [0-9]" "$f" || true)
        expected="${EXPECTED_STEPS[$id]}"
        if [ "$steps" = "$expected" ]; then
            ok "Experiment ${id}: ${steps} steps ✓"
        else
            fail "Experiment ${id}: ${steps} steps (expected ${expected})"
            all_ok=false
        fi
    else
        fail "Experiment ${id}: file not found"
        all_ok=false
    fi
done

# ── 8. docs.js Feature Check ───────────────────────────────────────────────

info "8. Frontend Code Feature Check"

DOCS_JS="/root/k8s-netlab/frontend/js/docs.js"

declare -A FEATURES=(
    ["buildStepNav"]="Step navigation builder"
    ["_renderPills"]="Step pill renderer"
    ["_scrollToStep"]="Scroll to step"
    ["_onDocScroll"]="Scroll listener"
    ["_toggleStep"]="Toggle step completion"
    ["_updateProgressBar"]="Progress bar updater"
    ["loadProgress"]="LocalStorage loader"
    ["saveProgress"]="LocalStorage saver"
    ["addCopyButton"]="Copy button (Phase 1)"
)

for fn in "${!FEATURES[@]}"; do
    if grep -q "${fn}(" "$DOCS_JS"; then
        ok "${FEATURES[$fn]} (${fn})"
    else
        fail "${FEATURES[$fn]} (${fn}) NOT FOUND in docs.js"
    fi
done

# ── 9. HTML Structure Check ────────────────────────────────────────────────

info "9. HTML Structure Check"

HTML="/root/k8s-netlab/frontend/index.html"

declare -A HTML_ELEMENTS=(
    ['id="step-nav"']="Step nav container"
    ['id="step-pills"']="Step pills container"
    ['id="step-progress-bar"']="Progress bar"
    ['id="step-progress-text"']="Progress text"
    ['lab-split-body']="Split body class"
    ['lab-doc-panel']="Doc panel class"
    ['lab-terminal-panel']="Terminal panel class"
    ['.step-pill']="Step pill CSS"
    ['@media (max-width: 768px)']="Responsive CSS"
)

for pattern in "${!HTML_ELEMENTS[@]}"; do
    if grep -q "$pattern" "$HTML"; then
        ok "${HTML_ELEMENTS[$pattern]}"
    else
        fail "${HTML_ELEMENTS[$pattern]} NOT FOUND in index.html"
    fi
done

# ── Summary ────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════"
echo "  Test Summary"
echo "════════════════════════════════════════"
echo -e "  ${GREEN}Passed:${NC}  ${PASS}"
echo -e "  ${RED}Failed:${NC}  ${FAIL}"
echo -e "  ${YELLOW}Skipped:${NC} ${SKIP}"
echo ""

TOTAL=$((PASS + FAIL))
if [ $TOTAL -gt 0 ]; then
    PCT=$(( PASS * 100 / TOTAL ))
    echo -e "  Pass rate: ${PCT}% (${PASS}/${TOTAL})"
fi

echo ""
if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}✅ ALL TESTS PASSED - Ready to release!${NC}"
    exit 0
else
    echo -e "  ${RED}❌ ${FAIL} TEST(S) FAILED - Fix before release${NC}"
    exit 1
fi
