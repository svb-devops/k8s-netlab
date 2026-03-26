#!/bin/bash
# PostToolUse hook — 仅对 systemctl restart k8s-netlab 触发
# stdin: JSON with tool_input.command

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('')
")

if [[ "$COMMAND" != "systemctl restart k8s-netlab" ]]; then
  exit 0
fi

echo "=== 部署后自动验证 (hook) ==="
sleep 3

HEALTH=$(curl -s https://lab.cloudnetops.tech/api/health 2>/dev/null)
echo "health: $HEALTH"

LOGS=$(journalctl -u k8s-netlab -p err --since "2 minutes ago" --no-pager 2>/dev/null | head -20)
if [[ -n "$LOGS" ]]; then
  echo "--- 错误日志 ---"
  echo "$LOGS"
else
  echo "错误日志: 无"
fi

if echo "$HEALTH" | grep -q '"status":"healthy"'; then
  exit 0
else
  echo "⚠️ 服务未健康！" >&2
  exit 1
fi
