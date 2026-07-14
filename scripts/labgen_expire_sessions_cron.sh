#!/usr/bin/env bash
# labgen_expire_sessions_cron.sh — 定时清理超时未关闭的 LabGen 学习者会话
#
# 背景：学生做完实验若不手动执行清理步骤（kubectl delete namespace）就直接关闭
# 浏览器，namespace 和其中的 Deployment/Pod/Service 会永久残留在集群里。后端已有
# POST /api/labgen/runtime/expire-sessions（admin-only）能按 TTL 识别并清理这些
# 会话，但从未被任何调度器调用过。本脚本负责登录 admin 账号并定时调用该接口。
#
# 用法（crontab，每 10 分钟一次）：
#   */10 * * * * bash /root/k8s-netlab/scripts/labgen_expire_sessions_cron.sh >> /var/log/labgen-session-expiry.log 2>&1
#
# 凭证来源（任选其一）：
#   1. 环境变量 LABGEN_CRON_ADMIN_USER / LABGEN_CRON_ADMIN_PASS
#   2. 凭证文件（默认 /root/.k8s-netlab-admin-credentials，格式 username=password），
#      默认取 smoke-admin 这一行
#
# 退出码：0 = 调用成功（无论是否有会话被清理）；1 = 登录失败或接口调用失败。

set -euo pipefail

BASE_URL="${LABGEN_CRON_BASE_URL:-http://localhost:8000}"
CRED_FILE="${LABGEN_CRON_CRED_FILE:-/root/.k8s-netlab-admin-credentials}"
ADMIN_USER="${LABGEN_CRON_ADMIN_USER:-}"
ADMIN_PASS="${LABGEN_CRON_ADMIN_PASS:-}"

if [ -z "$ADMIN_USER" ] || [ -z "$ADMIN_PASS" ]; then
    if [ -f "$CRED_FILE" ]; then
        line=$(grep -m1 '^smoke-admin=' "$CRED_FILE" || true)
        if [ -n "$line" ]; then
            ADMIN_USER="smoke-admin"
            ADMIN_PASS="${line#smoke-admin=}"
        fi
    fi
fi

if [ -z "$ADMIN_USER" ] || [ -z "$ADMIN_PASS" ]; then
    echo "[FATAL] 未配置 admin 凭证（设置 LABGEN_CRON_ADMIN_USER/LABGEN_CRON_ADMIN_PASS，或确认 ${CRED_FILE} 存在且含 smoke-admin= 一行）" >&2
    exit 1
fi

TMP_LOGIN_BODY="$(mktemp)"
TMP_RESULT_BODY="$(mktemp)"
TMP_LOGIN_PAYLOAD="$(mktemp)"
COOKIE_JAR="$(mktemp)"
chmod 600 "$TMP_LOGIN_PAYLOAD"

cleanup() {
    curl -s -o /dev/null -b "$COOKIE_JAR" -X POST "${BASE_URL}/api/auth/logout" || true
    rm -f "$TMP_LOGIN_BODY" "$TMP_RESULT_BODY" "$TMP_LOGIN_PAYLOAD" "$COOKIE_JAR"
}
trap cleanup EXIT

echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') [START] labgen_expire_sessions_cron"

# Login payload is written to a file (not passed as a -d/argv literal) so the
# admin password never appears in argv of this or the curl process — argv is
# world-readable via `ps auxww` / `/proc/<pid>/cmdline`; env vars are not
# (require matching uid or ptrace access), so pass credentials through the
# environment instead.
LABGEN_CRON_PAYLOAD_FILE="$TMP_LOGIN_PAYLOAD" LABGEN_CRON_PAYLOAD_USER="$ADMIN_USER" LABGEN_CRON_PAYLOAD_PASS="$ADMIN_PASS" \
    python3 -c '
import json, os
json.dump(
    {"username": os.environ["LABGEN_CRON_PAYLOAD_USER"], "password": os.environ["LABGEN_CRON_PAYLOAD_PASS"]},
    open(os.environ["LABGEN_CRON_PAYLOAD_FILE"], "w"),
)
'

login_status=$(curl -s -o "$TMP_LOGIN_BODY" -w "%{http_code}" \
    -c "$COOKIE_JAR" \
    -X POST "${BASE_URL}/api/auth/login" \
    -H "Content-Type: application/json" \
    --data-binary "@${TMP_LOGIN_PAYLOAD}")

if [ "$login_status" != "200" ]; then
    echo "[FATAL] admin 登录失败 (HTTP ${login_status})" >&2
    exit 1
fi

expire_status=$(curl -s -o "$TMP_RESULT_BODY" -w "%{http_code}" \
    -b "$COOKIE_JAR" \
    -X POST "${BASE_URL}/api/labgen/runtime/expire-sessions" \
    -H "Content-Type: application/json" \
    -d '{"dry_run": false}')

echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') expire-sessions HTTP ${expire_status}: $(cat "$TMP_RESULT_BODY")"

if [ "$expire_status" != "200" ]; then
    echo "[FATAL] /api/labgen/runtime/expire-sessions 调用失败" >&2
    exit 1
fi

exit 0
