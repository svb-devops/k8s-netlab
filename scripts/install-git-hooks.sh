#!/bin/bash
# ==========================================================
# K8S NetLab — Git Hook Installer
# Run once after cloning: bash scripts/install-git-hooks.sh
#
# Installs two security hooks:
#   pre-commit  — scans staged changes before every commit
#   pre-push    — scans pushed commits (catches --no-verify bypasses)
# ==========================================================

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$REPO_ROOT/.git/hooks"
PRECOMMIT_SCRIPT="$REPO_ROOT/scripts/pre-commit-security-check.sh"
PREPUSH_SCRIPT="$REPO_ROOT/scripts/pre-push-security-check.sh"

echo "=========================================="
echo "  安装 Git 安全检查 Hooks（双层防护）"
echo "=========================================="
echo ""

# Ensure check scripts are executable
chmod +x "$PRECOMMIT_SCRIPT"
echo "✅ pre-commit-security-check.sh 已设为可执行"

chmod +x "$PREPUSH_SCRIPT"
echo "✅ pre-push-security-check.sh 已设为可执行"

echo ""

# -------------------------------------------------------
# Layer 1: Install pre-commit hook
# -------------------------------------------------------
cat > "$HOOKS_DIR/pre-commit" << HOOK
#!/bin/bash
# Auto-installed by scripts/install-git-hooks.sh
# K8S NetLab security pre-commit hook (Layer 1)

REPO_ROOT=\$(git rev-parse --show-toplevel)

echo "运行 Git 安全检查..."
bash "\$REPO_ROOT/scripts/pre-commit-security-check.sh"

if [ \$? -ne 0 ]; then
    echo ""
    echo "⚠️  提交已阻止。请修复上述问题后重试。"
    echo "详细规范: docs/GIT-SECURITY-CHECKLIST.md"
    exit 1
fi
HOOK

chmod +x "$HOOKS_DIR/pre-commit"
echo "✅ .git/hooks/pre-commit 已安装（Layer 1 - 提交时检查）"

# -------------------------------------------------------
# Layer 2: Install pre-push hook
# -------------------------------------------------------
cat > "$HOOKS_DIR/pre-push" << HOOK
#!/bin/bash
# Auto-installed by scripts/install-git-hooks.sh
# K8S NetLab security pre-push hook (Layer 2)
# Catches commits that bypassed pre-commit with --no-verify

REPO_ROOT=\$(git rev-parse --show-toplevel)

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🔒 Git Pre-push 强制安全检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

bash "\$REPO_ROOT/scripts/pre-push-security-check.sh"

if [ \$? -ne 0 ]; then
    echo ""
    echo "⚠️  推送已阻止。请修复上述问题后重试。"
    echo "详细规范: docs/GIT-SECURITY-CHECKLIST.md"
    exit 1
fi
HOOK

chmod +x "$HOOKS_DIR/pre-push"
echo "✅ .git/hooks/pre-push 已安装（Layer 2 - 推送时检查）"

echo ""
echo "=========================================="
echo "  安装完成 — 双层安全防护已启用"
echo "=========================================="
echo ""
echo "  Layer 1: git commit → 自动扫描暂存区"
echo "  Layer 2: git push   → 自动扫描推送的commits"
echo ""
echo "可选：配置本地真实IP检测（不提交到Git）："
echo ""
echo "  cat > .security-config << 'EOF'"
echo "  export REAL_HOST_IP=\"your-actual-host-ip\""
echo "  export REAL_GATEWAY_IP=\"your-actual-gateway-ip\""
echo "  EOF"
echo ""
echo "详细使用说明: docs/GIT-SECURITY-CHECKLIST.md"
