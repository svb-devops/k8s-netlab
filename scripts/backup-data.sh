#!/usr/bin/env bash
# backup-data.sh — 每日备份 data/*.json 到 /root/backups/k8s-netlab/
# 保留最近 30 天，自动清理旧备份

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_ROOT="/root/backups/k8s-netlab"
DATE=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_ROOT/$DATE"

mkdir -p "$DEST"

# 备份 data/*.json（跳过 .lock 文件）
cp "$PROJECT_ROOT"/data/*.json "$DEST/" 2>/dev/null || true

FILE_COUNT=$(ls "$DEST"/*.json 2>/dev/null | wc -l)
if [ "$FILE_COUNT" -eq 0 ]; then
    echo "[backup] 警告：data/ 中无 JSON 文件可备份"
    exit 1
fi

echo "[backup] $DATE — 已备份 $FILE_COUNT 个文件到 $DEST"

# 保留最近 30 天，删除旧备份
find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true

KEPT=$(ls -d "$BACKUP_ROOT"/*/ 2>/dev/null | wc -l)
echo "[backup] 当前保留备份数量：$KEPT"
