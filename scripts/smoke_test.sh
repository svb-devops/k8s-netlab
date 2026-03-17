#!/usr/bin/env bash
# smoke_test.sh — 部署后快速验收 5 个核心端点
#
# 用法：
#   bash scripts/smoke_test.sh <BASE_URL> <TEST_USER> <TEST_PASS> [ADMIN_TOKEN]
#
# 示例：
#   bash scripts/smoke_test.sh http://localhost:8000 smokeuser smokepass123 myAdminToken
#
# 全部通过退出码 0，任一失败退出码 1。

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
TEST_USER="${2:-smokeuser}"
TEST_PASS="${3:-smokepass123}"
ADMIN_TOKEN="${4:-}"

PASS=0
FAIL=0
COOKIE_JAR="$(mktemp)"

log_ok()   { echo "[OK]   $1"; PASS=$((PASS+1)); }
log_fail() { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }

cleanup() { rm -f "$COOKIE_JAR"; }
trap cleanup EXIT

# -------------------------------------------------------
# 检查 1：GET /api/health → 200，status 字段存在
# -------------------------------------------------------
resp=$(curl -s -o /tmp/smoke_body -w "%{http_code}" "${BASE_URL}/api/health")
if [ "$resp" = "200" ] && grep -q '"status"' /tmp/smoke_body; then
    log_ok "GET /api/health → 200"
else
    log_fail "GET /api/health → 期望 200，实际 ${resp}，body: $(cat /tmp/smoke_body)"
fi

# -------------------------------------------------------
# 准备：注册测试用户（忽略 400 重复注册）
# -------------------------------------------------------
curl -s -o /dev/null -X POST "${BASE_URL}/api/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${TEST_USER}\",\"password\":\"${TEST_PASS}\"}" || true

# -------------------------------------------------------
# 检查 2：POST /api/auth/login → 200，设置 cookie
# -------------------------------------------------------
resp=$(curl -s -o /tmp/smoke_body -w "%{http_code}" \
    -c "$COOKIE_JAR" \
    -X POST "${BASE_URL}/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${TEST_USER}\",\"password\":\"${TEST_PASS}\"}")
if [ "$resp" = "200" ] && grep -q "session_token" "$COOKIE_JAR"; then
    log_ok "POST /api/auth/login → 200 + cookie"
else
    log_fail "POST /api/auth/login → 期望 200+cookie，实际 ${resp}"
fi

# -------------------------------------------------------
# 检查 3：GET /api/auth/me → 200，username 正确
# -------------------------------------------------------
resp=$(curl -s -o /tmp/smoke_body -w "%{http_code}" \
    -b "$COOKIE_JAR" \
    "${BASE_URL}/api/auth/me")
if [ "$resp" = "200" ] && grep -q "\"${TEST_USER}\"" /tmp/smoke_body; then
    log_ok "GET /api/auth/me → 200, username=${TEST_USER}"
else
    log_fail "GET /api/auth/me → 期望 200+username，实际 ${resp}，body: $(cat /tmp/smoke_body)"
fi

# -------------------------------------------------------
# 检查 4：GET /api/experiments → 200，列表非空
# -------------------------------------------------------
resp=$(curl -s -o /tmp/smoke_body -w "%{http_code}" \
    "${BASE_URL}/api/experiments")
if [ "$resp" = "200" ] && grep -q '"experiments"' /tmp/smoke_body; then
    log_ok "GET /api/experiments → 200"
else
    log_fail "GET /api/experiments → 期望 200+experiments，实际 ${resp}"
fi

# -------------------------------------------------------
# 检查 5：GET /api/admin/status → 200（需要 ADMIN_TOKEN）
# -------------------------------------------------------
if [ -n "$ADMIN_TOKEN" ]; then
    resp=$(curl -s -o /tmp/smoke_body -w "%{http_code}" \
        -H "X-Admin-Token: ${ADMIN_TOKEN}" \
        "${BASE_URL}/api/admin/status")
    if [ "$resp" = "200" ] && grep -q '"stats"' /tmp/smoke_body; then
        log_ok "GET /api/admin/status → 200"
    else
        log_fail "GET /api/admin/status → 期望 200+stats，实际 ${resp}"
    fi
else
    echo "[SKIP] GET /api/admin/status（未提供 ADMIN_TOKEN）"
fi

# -------------------------------------------------------
# 清理：登出
# -------------------------------------------------------
curl -s -o /dev/null -b "$COOKIE_JAR" -X POST "${BASE_URL}/api/auth/logout" || true

# -------------------------------------------------------
# 汇总
# -------------------------------------------------------
echo ""
echo "冒烟测试完成：通过 ${PASS}，失败 ${FAIL}"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
