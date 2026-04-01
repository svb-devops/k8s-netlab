#!/bin/bash
# ==========================================================
# K8S NetLab — Pre-push Security Check
#
# Called by .git/hooks/pre-push with push range on stdin.
# Scans every commit being pushed for sensitive data.
#
# Usage: called automatically by git push
#        or manually: bash scripts/pre-push-security-check.sh <range>
# ==========================================================

set -uo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

ISSUES=0
ZERO="0000000000000000000000000000000000000000"

# ----------------------------------------------------------------
# Determine range to check
# ----------------------------------------------------------------
# When called from hook: range comes from stdin (git format)
# When called manually:  range is $1
# ----------------------------------------------------------------
get_diff_for_range() {
    local range="$1"
    git diff "$range" 2>/dev/null || true
}

check_range() {
    local local_sha="$1"
    local remote_sha="$2"

    # Deleted branch — nothing to check
    [ "$local_sha" = "$ZERO" ] && return 0

    if [ "$remote_sha" = "$ZERO" ]; then
        # New branch: check all commits reachable from local_sha
        range="$local_sha"
    else
        # Existing branch: check only new commits
        range="$remote_sha..$local_sha"
    fi

    echo ""
    echo "扫描范围: $range"
    local DIFF
    DIFF=$(git diff "$range" 2>/dev/null || true)

    if [ -z "$DIFF" ]; then
        echo "  (无新增内容)"
        return 0
    fi

    local ADDED
    ADDED=$(echo "$DIFF" | grep "^+" | grep -v "^+++" || true)

    # Load project-specific real IP from local config (not committed)
    REAL_IP_PATTERN=""
    if [ -f ".security-config" ]; then
        # shellcheck source=/dev/null
        source .security-config 2>/dev/null || true
        if [ -n "${REAL_HOST_IP:-}" ]; then
            ESCAPED=$(echo "$REAL_HOST_IP" | sed 's/\./\\./g')
            REAL_IP_PATTERN="$ESCAPED"
        fi
        if [ -n "${REAL_GATEWAY_IP:-}" ]; then
            ESCAPED=$(echo "$REAL_GATEWAY_IP" | sed 's/\./\\./g')
            REAL_IP_PATTERN="${REAL_IP_PATTERN:+$REAL_IP_PATTERN|}$ESCAPED"
        fi
    fi

    # ------------------------------------------------------------------
    # 1. Plaintext passwords
    # ------------------------------------------------------------------
    echo "  [1/8] 明文密码..."
    if echo "$ADDED" | grep -iE '(password|passwd|pwd)\s*=\s*["\x27][^"\x27]{4,}["\x27]' \
        | grep -v 'your-password\|example\|<PASSWORD>\|getenv\|os\.environ\|\.env' \
        | grep -qE '.'; then
        echo "  ❌ 发现明文密码"
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi

    # ------------------------------------------------------------------
    # 2. API keys and tokens
    # ------------------------------------------------------------------
    echo "  [2/8] API密钥和Token..."
    if echo "$ADDED" | grep -iE '(api_key|apikey|secret_key|access_key)\s*=\s*["\x27][A-Za-z0-9_\-]{10,}["\x27]' \
        | grep -v 'your-key\|example\|<.*KEY.*>\|getenv\|os\.environ' \
        | grep -qE '.'; then
        echo "  ❌ 发现API密钥"
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi

    # ------------------------------------------------------------------
    # 3. Private key files
    # ------------------------------------------------------------------
    echo "  [3/8] 私钥文件..."
    KEY_FILES=$(git diff --name-only "$range" 2>/dev/null | grep -E '\.(key|pem|p12|pfx)$' || true)
    if [ -n "$KEY_FILES" ]; then
        echo "  ❌ 发现私钥文件: $KEY_FILES"
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi

    # ------------------------------------------------------------------
    # 4. .env files
    # ------------------------------------------------------------------
    echo "  [4/8] .env配置文件..."
    ENV_FILES=$(git diff --name-only "$range" 2>/dev/null \
        | grep -E '(^|/)\.env($|\.)' \
        | grep -v '\.example$\|\.sample$\|\.template$' || true)
    if [ -n "$ENV_FILES" ]; then
        echo "  ❌ 发现.env文件: $ENV_FILES"
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi

    # ------------------------------------------------------------------
    # 5. Real IP addresses
    # ------------------------------------------------------------------
    echo "  [5/8] 真实IP地址..."
    IP_FOUND=0

    # Project-specific IPs from .security-config
    if [ -n "$REAL_IP_PATTERN" ]; then
        if echo "$ADDED" | grep -E "$REAL_IP_PATTERN" \
            | grep -qv 'example\|示例\|<.*IP.*>'; then
            echo "  ❌ 发现项目真实IP"
            IP_FOUND=1
        fi
    fi

    # IPs embedded in URLs or SSH commands
    if echo "$ADDED" \
        | grep -E '(https?://|ssh\s+\w+@)[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}' \
        | grep -qv 'example\|示例\|<.*>\|8\.8\.[48]\.[48]\|127\.0\.0\.1\|0\.0\.0\.0'; then
        echo "  ❌ 发现URL/SSH中含有真实IP"
        IP_FOUND=1
    fi

    if [ $IP_FOUND -eq 1 ]; then
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi

    # ------------------------------------------------------------------
    # 6. User data files
    # ------------------------------------------------------------------
    echo "  [6/8] 用户数据文件..."
    DATA_FILES=$(git diff --name-only "$range" 2>/dev/null \
        | grep -iE 'users?\.json|data/.*\.(json|db|sqlite)|sessions\.json' || true)
    if [ -n "$DATA_FILES" ]; then
        echo "  ❌ 发现用户数据文件: $DATA_FILES"
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi

    # ------------------------------------------------------------------
    # 7. Database connection strings
    # ------------------------------------------------------------------
    echo "  [7/8] 数据库连接字符串..."
    if echo "$ADDED" | grep -iE '(mysql|postgresql|mongodb|redis)://[^/\s]+:[^@\s]+@' \
        | grep -qE '.'; then
        echo "  ❌ 发现数据库连接字符串（含密码）"
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi

    # ------------------------------------------------------------------
    # 8. Commit messages
    # ------------------------------------------------------------------
    echo "  [8/8] Commit message敏感内容..."
    BAD_MSGS=0
    for commit in $(git rev-list "$range" 2>/dev/null); do
        MSG=$(git log -1 --pretty=format:"%B" "$commit")
        if echo "$MSG" | grep -iE '(password|api_key)\s*=|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}' \
            | grep -qv 'example\|示例\|<.*>'; then
            BAD_MSGS=$((BAD_MSGS + 1))
        fi
    done
    if [ $BAD_MSGS -gt 0 ]; then
        echo "  ❌ 发现 $BAD_MSGS 个commit message含敏感内容"
        ISSUES=$((ISSUES + 1))
    else
        echo "  ✅ 通过"
    fi
}

# ----------------------------------------------------------------
# Main: process each ref being pushed (from stdin or argument)
# ----------------------------------------------------------------
if [ $# -ge 2 ]; then
    # Called manually with range: local_sha remote_sha
    check_range "$1" "$2"
else
    # Called from git hook: read refs from stdin
    CHECKED=0
    while read -r local_ref local_sha remote_ref remote_sha; do
        check_range "$local_sha" "$remote_sha"
        CHECKED=$((CHECKED + 1))
    done

    if [ "$CHECKED" -eq 0 ]; then
        echo "  (没有需要推送的提交)"
    fi
fi

# ----------------------------------------------------------------
# Codex 独立代码审查（OpenAI 模型，真正独立于 Claude）
# ----------------------------------------------------------------
if [ "$ISSUES" -eq 0 ] && command -v codex &>/dev/null; then
    echo ""
    echo "  [Codex] 独立代码审查（gpt-5.3-codex）..."
    CODEX_OUTPUT=$(timeout 120 codex review --base main 2>&1 || true)
    if echo "$CODEX_OUTPUT" | grep -qi "quota exceeded\|unauthorized\|401\|rate limit"; then
        echo "  ⚠️  Codex 账户未就绪（配额/认证问题），跳过独立审查"
        echo "  请检查 platform.openai.com 账户余额后重新 push"
    elif echo "$CODEX_OUTPUT" | grep -qiE "^[-*]?\s*Severity:\s*BLOCKER|^\s*BLOCKER:"; then
        echo "  ❌ Codex 发现 BLOCKER，push 已阻止："
        echo "$CODEX_OUTPUT" | grep -iE "^[-*]?\s*Severity:\s*BLOCKER|^\s*BLOCKER:" | sed 's/^/     /'
        ISSUES=$((ISSUES + 1))
    elif echo "$CODEX_OUTPUT" | grep -qi "error\|failed\|interrupted"; then
        echo "  ⚠️  Codex 运行异常，跳过（不阻断 push）"
    else
        echo "  ✅ Codex 审查通过"
    fi
fi

# ----------------------------------------------------------------
# 测试门禁：有 tests/ 目录则必须通过
# ----------------------------------------------------------------
if [ -d "tests" ] && [ "$ISSUES" -eq 0 ]; then
    echo ""
    echo "  [测试] 运行 pytest..."
    VENV_PYTHON="$PROJECT_ROOT/venv/bin/python3"
    PYTEST_BIN="${PROJECT_ROOT}/venv/bin/pytest"
    if [ -f "$PYTEST_BIN" ]; then
        PYTEST_CMD="$PYTEST_BIN"
    else
        PYTEST_CMD="python3 -m pytest"
    fi
    if $PYTEST_CMD tests/ -x -q --tb=short 2>&1 | sed 's/^/  /'; then
        echo "  ✅ 测试通过"
    else
        echo "  ❌ 测试失败，push 已阻止"
        echo "  修复测试后重新推送"
        exit 1
    fi
fi

# ----------------------------------------------------------------
# Result
# ----------------------------------------------------------------
echo ""
echo "=========================================="
if [ "$ISSUES" -eq 0 ]; then
    echo "✅ Pre-push安全检查通过！"
    echo "=========================================="
    exit 0
else
    echo "❌ 发现 $ISSUES 个问题，推送已阻止！"
    echo ""
    echo "处理建议："
    echo "  1. 移除敏感信息"
    echo "  2. 修改commit: git commit --amend"
    echo "  3. 修改历史:   git rebase -i HEAD~N"
    echo "  4. 重新推送:   git push"
    echo ""
    echo "详细规范: docs/GIT-SECURITY-CHECKLIST.md"
    echo "=========================================="
    exit 1
fi
