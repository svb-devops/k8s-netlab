#!/bin/bash
# ==========================================================
# K8S NetLab — Pre-commit Security Check
# Run before every git commit to prevent leaking sensitive data
# Usage: bash scripts/pre-commit-security-check.sh
# ==========================================================

set -euo pipefail

echo "=========================================="
echo "  Git提交前安全检查"
echo "=========================================="
echo ""

PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

ISSUES=0

# Load project-specific real IP patterns from local non-committed config
# Create .security-config with your real IPs (it's in .gitignore)
REAL_IP_PATTERN=""
if [ -f ".security-config" ]; then
    # shellcheck source=/dev/null
    source .security-config
    # Build grep pattern from env vars (escaping dots)
    if [ -n "${REAL_HOST_IP:-}" ]; then
        ESCAPED=$(echo "$REAL_HOST_IP" | sed 's/\./\\./g')
        REAL_IP_PATTERN="$ESCAPED"
    fi
    if [ -n "${REAL_GATEWAY_IP:-}" ]; then
        ESCAPED=$(echo "$REAL_GATEWAY_IP" | sed 's/\./\\./g')
        REAL_IP_PATTERN="${REAL_IP_PATTERN:+$REAL_IP_PATTERN|}$ESCAPED"
    fi
fi

# ----------------------------------------------------------
# 1. Plaintext passwords
# ----------------------------------------------------------
echo "【1/8】检查明文密码..."
if git diff --cached | grep -E '^[+]' \
    | grep -iE '(password|passwd|pwd)\s*=\s*["\x27][^"\x27]{4,}["\x27]' \
    | grep -v 'your-password\|example\|<PASSWORD>\|getenv\|os\.environ\|\.env'; then
    echo "❌ 发现明文密码！"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ 通过"
fi

# ----------------------------------------------------------
# 2. API keys and tokens
# ----------------------------------------------------------
echo "【2/8】检查API密钥和Token..."
if git diff --cached | grep -E '^[+]' \
    | grep -iE '(api_key|apikey|secret_key|access_key)\s*=\s*["\x27][A-Za-z0-9_\-]{10,}["\x27]' \
    | grep -v 'your-key\|example\|<.*KEY.*>\|getenv\|os\.environ'; then
    echo "❌ 发现API密钥！"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ 通过"
fi

# ----------------------------------------------------------
# 3. Private key files
# ----------------------------------------------------------
echo "【3/8】检查私钥文件..."
KEY_FILES=$(git diff --cached --name-only | grep -E '\.(key|pem|p12|pfx)$' || true)
if [ -n "$KEY_FILES" ]; then
    echo "❌ 发现私钥文件: $KEY_FILES"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ 通过"
fi

# ----------------------------------------------------------
# 4. .env files
# ----------------------------------------------------------
echo "【4/8】检查.env配置文件..."
ENV_FILES=$(git diff --cached --name-only | grep -E '(^|/)\.env($|\.)' | grep -v '\.example$\|\.sample$\|\.template$' || true)
if [ -n "$ENV_FILES" ]; then
    echo "❌ 发现.env文件: $ENV_FILES"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ 通过"
fi

# ----------------------------------------------------------
# 5. Real IP addresses (project-specific + generic private ranges)
# ----------------------------------------------------------
echo "【5/8】检查真实IP地址..."
IP_FOUND=0

# Check project-specific IPs from .security-config
if [ -n "$REAL_IP_PATTERN" ]; then
    if git diff --cached | grep -E '^[+]' \
        | grep -E "$REAL_IP_PATTERN" \
        | grep -v 'example\|示例\|<.*IP.*>'; then
        echo "❌ 发现项目真实IP地址！"
        IP_FOUND=1
    fi
fi

# Generic: check for private-range host IPs embedded in non-example contexts
# (any x.x.x.N where N > 1 suggesting a specific host, not a gateway)
if git diff --cached | grep -E '^[+]' \
    | grep -E '(https?://|ssh\s+\w+@)[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}' \
    | grep -v 'example\|示例\|<.*>\|8\.8\.[48]\.[48]\|127\.0\.0\.1\|0\.0\.0\.0'; then
    echo "❌ 发现URL/SSH中含有具体IP地址！"
    IP_FOUND=1
fi

if [ $IP_FOUND -eq 0 ]; then
    echo "✅ 通过"
else
    ISSUES=$((ISSUES + 1))
fi

# ----------------------------------------------------------
# 6. User data files
# ----------------------------------------------------------
echo "【6/8】检查用户数据文件..."
DATA_FILES=$(git diff --cached --name-only \
    | grep -iE 'users?\.json|data/.*\.(json|db|sqlite)|sessions\.json' || true)
if [ -n "$DATA_FILES" ]; then
    echo "❌ 发现用户数据文件: $DATA_FILES"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ 通过"
fi

# ----------------------------------------------------------
# 7. Database connection strings
# ----------------------------------------------------------
echo "【7/8】检查数据库连接字符串..."
if git diff --cached | grep -E '^[+]' \
    | grep -iE '(mysql|postgresql|mongodb|redis)://[^/\s]+:[^@\s]+@'; then
    echo "❌ 发现数据库连接字符串（含密码）！"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ 通过"
fi

# ----------------------------------------------------------
# 8. SSH connection strings with real hosts
# ----------------------------------------------------------
echo "【8/8】检查SSH连接信息..."
if git diff --cached | grep -E '^[+]' \
    | grep -E 'ssh\s+[a-zA-Z0-9_]+@[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
    | grep -v 'example\|<.*>'; then
    echo "❌ 发现带真实IP的SSH连接命令！"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ 通过"
fi

# ----------------------------------------------------------
# Result
# ----------------------------------------------------------
echo ""
echo "=========================================="
if [ "$ISSUES" -eq 0 ]; then
    echo "✅ 安全检查通过！可以提交"
    echo "=========================================="
    exit 0
else
    echo "❌ 发现 $ISSUES 个问题，提交已阻止！"
    echo ""
    echo "处理建议："
    echo "  1. 移除敏感信息"
    echo "  2. 密码/密钥 → 使用环境变量: os.getenv('VAR')"
    echo "  3. 真实IP → 使用占位符: <HOST_IP>"
    echo "  4. 敏感文件 → 添加到 .gitignore"
    echo ""
    echo "详细规范: docs/GIT-SECURITY-CHECKLIST.md"
    echo ""
    echo "如需跳过（仅限紧急情况，需团队审批）："
    echo "  git commit --no-verify"
    echo "=========================================="
    exit 1
fi
