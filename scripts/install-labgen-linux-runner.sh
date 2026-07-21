#!/bin/bash
# Idempotent install of the labgen-linux-runner system account used to run
# Linux-domain learner commands with real privilege separation from the
# root-owned k8s-netlab API process. Safe to run multiple times.
set -euo pipefail

CONF_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/systemd/labgen-linux-runner.sysusers.conf"
CONF_DST="/etc/sysusers.d/labgen-linux-runner.conf"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must run as root (creates a system user)" >&2
    exit 1
fi

cp "$CONF_SRC" "$CONF_DST"
systemd-sysusers "$CONF_DST"

RUNNER_UID="$(id -u labgen-linux-runner)"
RUNNER_GID="$(id -g labgen-linux-runner)"

if [ "$RUNNER_UID" -eq 0 ] || [ "$RUNNER_GID" -eq 0 ]; then
    echo "ERROR: labgen-linux-runner resolved to UID/GID 0 — refusing to proceed" >&2
    exit 1
fi

SUPPLEMENTARY_GROUPS="$(id -Gn labgen-linux-runner | tr ' ' '\n' | grep -v '^labgen-linux-runner$' || true)"
if [ -n "$SUPPLEMENTARY_GROUPS" ]; then
    echo "ERROR: labgen-linux-runner has unexpected supplementary groups: $SUPPLEMENTARY_GROUPS" >&2
    exit 1
fi

echo "labgen-linux-runner ready: uid=$RUNNER_UID gid=$RUNNER_GID, no supplementary groups"
