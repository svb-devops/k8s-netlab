#!/bin/bash
# ==========================================================
# K8S NetLab — Git Hook Installer
# Run once after cloning: bash scripts/install-git-hooks.sh
# ==========================================================

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$REPO_ROOT/.git/hooks"
SCRIPT="$REPO_ROOT/scripts/pre-commit-security-check.sh"

echo "=========================================="
echo "  安装 Git 安全检查 Hook"
echo "=========================================="
echo ""

# Ensure the check script is executable
chmod +x "$SCRIPT"
echo "✅ pre-commit-security-check.sh 已设为可执行"

# Install pre-commit hook
cat > "$HOOKS_DIR/pre-commit" << HOOK
#!/bin/bash
# Auto-installed by scripts/install-git-hooks.sh
# K8S NetLab security pre-commit hook

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
echo "✅ .git/hooks/pre-commit 已安装"

echo ""
echo "=========================================="
echo "  安装完成"
echo "=========================================="
echo ""
echo "现在每次 'git commit' 前都会自动运行安全检查。"
echo ""
echo "可选：创建本地IP检测配置（不提交到Git）："
echo ""
echo "  cat > .security-config << 'EOF'"
echo "  export REAL_HOST_IP=\"your-actual-host-ip\""
echo "  export REAL_GATEWAY_IP=\"your-actual-gateway-ip\""
echo "  EOF"
echo ""
echo "详细使用说明: docs/GIT-SECURITY-CHECKLIST.md"
