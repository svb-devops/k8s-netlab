#!/usr/bin/env bash
# run-data-retention-cron.sh — scheduled wrapper for DataRetentionService.
#
# Runs scripts/run_data_retention.py --execute under a non-blocking flock so
# an overlapping invocation (e.g. a manual run racing the timer) exits
# immediately instead of running concurrently against the same data files.
#
# Scheduled via the k8s-netlab-data-retention systemd timer (see
# docs/ops/LIMITED_AVAILABILITY_OPERATING_MODE_v1.0.md) — not cron directly,
# since this host is not 24x7 and the timer's Persistent=true catches up a
# missed run on next boot.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_FILE="/var/lock/k8s-netlab-data-retention.lock"

log() {
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "[FATAL] another data-retention run is already in progress, exiting"
    exit 1
fi

log "[START] data-retention"
cd "$PROJECT_ROOT"
source venv/bin/activate
python3 scripts/run_data_retention.py --execute
STATUS=$?
log "[DONE] data-retention exit=$STATUS"
exit "$STATUS"
