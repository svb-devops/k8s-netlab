#!/usr/bin/env bash
# stability_watch.sh — Non-invasive 24h stability watch for k8s-netlab.
# Runs every 30 minutes via cron. Appends JSON-structured results to log file.
#
# GUARANTEES:
#   - Does NOT create lab sessions, VMs, trigger LLM, modify data, expose secrets
#   - Safe to run repeatedly without side effects
#   - Exit 0 on pass or warn; exit 1 on fail
#
# Usage: bash scripts/stability_watch.sh [/path/to/logfile]
# Default log: /var/log/k8s-netlab-stability-watch.log

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="/var/log/k8s-netlab-stability-watch.log"
[ $# -ge 1 ] && LOG_FILE="$1"

TS=$(date -Iseconds)
EPOCH=$(date +%s)
WARNINGS=""
ERRORS=""
STATUS="pass"

add_warning() { WARNINGS="${WARNINGS:+$WARNINGS|}$1"; STATUS="warn"; }
add_error()   { ERRORS="${ERRORS:+$ERRORS|}$1";     STATUS="fail"; }

# 1. Service health + sub-statuses
HEALTH=$(curl -sf --max-time 10 https://lab.cloudnetops.tech/api/health 2>/dev/null || true)
if echo "$HEALTH" | grep -q '"healthy"' 2>/dev/null; then
    SVC_STATUS="healthy"
    LABGEN_STATUS=$(python3 -c "import sys,json; d=json.loads('$HEALTH'.replace(\"'\",\"'\")); print(d.get('labgen',{}).get('status','?'))" 2>/dev/null || echo "?")
    SESSION_STATUS=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('sessions',{}).get('status','?'))" "$HEALTH" 2>/dev/null || echo "?")
    ACTIVE_CT=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('sessions',{}).get('active_session_count',0))" "$HEALTH" 2>/dev/null || echo 0)
    FAILED_CT=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('sessions',{}).get('failed_terminal_session_count',0))" "$HEALTH" 2>/dev/null || echo 0)
    TAINTED_CT=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('sessions',{}).get('tainted_vm_count',0))" "$HEALTH" 2>/dev/null || echo 0)
    [ "$LABGEN_STATUS" != "ok" ] && add_warning "labgen_status=$LABGEN_STATUS"
    [ "$SESSION_STATUS" != "ok" ] && add_warning "sessions_status=$SESSION_STATUS"
    [ "${FAILED_CT:-0}" -gt 0 ] 2>/dev/null && add_error "failed_sessions=$FAILED_CT"
    [ "${TAINTED_CT:-0}" -gt 0 ] 2>/dev/null && add_warning "tainted_vms=$TAINTED_CT"
else
    SVC_STATUS="unhealthy"
    LABGEN_STATUS="?"; SESSION_STATUS="?"; ACTIVE_CT=0; FAILED_CT=0; TAINTED_CT=0
    add_error "health_endpoint_unreachable"
fi

# 2. Error logs (last 35 min)
ERR_COUNT=0
ERR_COUNT=$(journalctl -u k8s-netlab -p err --since "35 minutes ago" --no-pager 2>/dev/null | grep -vc "^--" 2>/dev/null | tr -d '[:space:]') || true
ERR_COUNT="${ERR_COUNT:-0}"
[ "$ERR_COUNT" -gt 0 ] 2>/dev/null && add_error "err_log_count=$ERR_COUNT"

# 3. VMID 500-599 (warn if VMs present — they may be active learner VMs)
VMID_599=""
if command -v qm &>/dev/null; then
    VMID_599=$(qm list 2>/dev/null | awk 'NR>1 {print $1}' | grep -E '^5[0-9]{2}$' | tr '\n' ',' | sed 's/,$//' || true)
    [ -n "$VMID_599" ] && add_warning "vmid_500_599_active=${VMID_599}"
fi

# 4. Data file growth
DIFFS_KB=0
if [ -f "$PROJECT_ROOT/data/lab_review_diffs.json" ]; then
    DIFFS_KB=$(du -k "$PROJECT_ROOT/data/lab_review_diffs.json" | cut -f1 || echo 0)
    [ "${DIFFS_KB:-0}" -gt 1024 ] && add_warning "diffs_file_${DIFFS_KB}KB_exceeds_1MB"
fi

# 5. Disk usage
DISK_PCT=$(df /root 2>/dev/null | awk 'NR==2{gsub(/%/,""); print $5}' || echo 0)
[ "${DISK_PCT:-0}" -gt 85 ] 2>/dev/null && add_warning "disk_${DISK_PCT}pct"

# 6. Memory
MEM_PCT=$(free 2>/dev/null | awk '/^Mem:/{printf "%.0f", $3/$2*100}' || echo 0)
[ "${MEM_PCT:-0}" -gt 90 ] 2>/dev/null && add_warning "mem_${MEM_PCT}pct"

# 7. Owner Article #1
ARTICLE_OK="unknown"
ARTICLE_RESP=$(curl -sf --max-time 10 "https://lab.cloudnetops.tech/api/articles/crashloopbackoff-describe-logs" 2>/dev/null || true)
if [ -n "$ARTICLE_RESP" ]; then
    ARTICLE_OK=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print('ok' if d.get('slug') else 'missing')" "$ARTICLE_RESP" 2>/dev/null || echo "error")
else
    ARTICLE_OK="unreachable"
fi
[ "$ARTICLE_OK" != "ok" ] && add_warning "owner_article_1=$ARTICLE_OK"

# 8. CTA
CTA_OK="unknown"
CTA_RESP=$(curl -sf --max-time 10 "https://lab.cloudnetops.tech/api/articles/crashloopbackoff-describe-logs/lab-cta" 2>/dev/null || true)
if [ -n "$CTA_RESP" ]; then
    CTA_OK=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print('ok' if d.get('has_cta') else 'missing')" "$CTA_RESP" 2>/dev/null || echo "error")
else
    CTA_OK="unreachable"
fi
[ "$CTA_OK" != "ok" ] && add_warning "cta=$CTA_OK"

# 9. Git dirty working tree
GIT_DIRTY=0
GIT_DIRTY=$(git -C "$PROJECT_ROOT" status --short 2>/dev/null | grep -c "" || echo 0)
[ "${GIT_DIRTY:-0}" -gt 0 ] 2>/dev/null && add_warning "dirty_working_tree=${GIT_DIRTY}_files"

# 10. cloudflared
CF_OK="ok"
pgrep -x cloudflared &>/dev/null || { CF_OK="down"; add_error "cloudflared_down"; }

# Strip any trailing whitespace/newlines from numeric variables before JSON
ERR_COUNT=$(printf '%s' "${ERR_COUNT:-0}" | tr -d '[:space:]')
DIFFS_KB=$(printf '%s' "${DIFFS_KB:-0}" | tr -d '[:space:]')
DISK_PCT=$(printf '%s' "${DISK_PCT:-0}" | tr -d '[:space:]')
MEM_PCT=$(printf '%s' "${MEM_PCT:-0}" | tr -d '[:space:]')
GIT_DIRTY=$(printf '%s' "${GIT_DIRTY:-0}" | tr -d '[:space:]')
ACTIVE_CT=$(printf '%s' "${ACTIVE_CT:-0}" | tr -d '[:space:]')
FAILED_CT=$(printf '%s' "${FAILED_CT:-0}" | tr -d '[:space:]')
TAINTED_CT=$(printf '%s' "${TAINTED_CT:-0}" | tr -d '[:space:]')
EPOCH=$(printf '%s' "${EPOCH:-0}" | tr -d '[:space:]')

# Write result as JSON line using env vars to avoid heredoc interpolation issues
export _SW_TS="$TS" _SW_EPOCH="$EPOCH" _SW_SVC="$SVC_STATUS" _SW_LABGEN="$LABGEN_STATUS"
export _SW_SESS="$SESSION_STATUS" _SW_ACT="$ACTIVE_CT" _SW_FAIL="$FAILED_CT" _SW_TAINT="$TAINTED_CT"
export _SW_ERR="$ERR_COUNT" _SW_VMID="${VMID_599:-none}" _SW_DIFFS="$DIFFS_KB"
export _SW_DISK="$DISK_PCT" _SW_MEM="$MEM_PCT" _SW_ART="$ARTICLE_OK" _SW_CTA="$CTA_OK"
export _SW_GIT="$GIT_DIRTY" _SW_CF="$CF_OK" _SW_STATUS="$STATUS"
export _SW_WARN="${WARNINGS:-none}" _SW_ERRS="${ERRORS:-none}" _SW_LOG="$LOG_FILE"

python3 -c "
import json, os
e = os.environ
result = {
    'ts': e['_SW_TS'], 'epoch': int(e['_SW_EPOCH']),
    'svc': e['_SW_SVC'], 'labgen': e['_SW_LABGEN'], 'sessions': e['_SW_SESS'],
    'active': int(e['_SW_ACT']), 'failed': int(e['_SW_FAIL']), 'tainted': int(e['_SW_TAINT']),
    'err_logs': int(e['_SW_ERR']), 'vmid_500_599': e['_SW_VMID'],
    'diffs_kb': int(e['_SW_DIFFS']), 'disk_pct': int(e['_SW_DISK']), 'mem_pct': int(e['_SW_MEM']),
    'article1': e['_SW_ART'], 'cta': e['_SW_CTA'],
    'git_dirty': int(e['_SW_GIT']), 'cloudflared': e['_SW_CF'],
    'status': e['_SW_STATUS'], 'warnings': e['_SW_WARN'], 'errors': e['_SW_ERRS'],
}
with open(e['_SW_LOG'], 'a') as f:
    f.write(json.dumps(result) + '\n')
"

# Print summary to stderr (captured by cron mail)
if [ "$STATUS" = "fail" ]; then
    echo "[FAIL] $TS k8s-netlab stability_watch: errors=${ERRORS:-none} warnings=${WARNINGS:-none}" >&2
    exit 1
elif [ "$STATUS" = "warn" ]; then
    echo "[WARN] $TS k8s-netlab stability_watch: warnings=${WARNINGS:-none}" >&2
    exit 0
else
    echo "[PASS] $TS k8s-netlab stability_watch: all checks ok" >&2
    exit 0
fi
