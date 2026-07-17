#!/usr/bin/env bash
# backup-full-state.sh — 每日一致性全量备份编排器
#
# 覆盖范围：data/*.json（复用 backup-data.sh）+ Directus PostgreSQL + uploads +
# extensions（backup-directus.sh），产出统一的 manifest.json（时间戳/文件名/大小/
# SHA-256/Postgres 版本）。
#
# 用法（crontab，每日一次，与现有 backup-data.sh 03:00 错开）：
#   30 3 * * * /root/k8s-netlab/scripts/backup-full-state.sh >> /var/log/k8s-netlab-backup-full-state.log 2>&1
#
# 设计要点：
#   - flock 独占锁，防止并发执行
#   - 先在 staging 临时目录内产出全部文件并校验 checksum，全部通过后才原子 mv 到
#     正式备份目录（同一文件系统内 mv 是原子操作）；任何一步失败，staging 目录
#     被清理，不留半成品，不产出到正式目录
#   - 目录权限 700，备份文件权限 600
#   - 不备份 .env / .env.directus 本身，只在 manifest 里记录需要哪个配置文件路径
#     用于恢复
#   - 保留最近 30 天，清理时不会删除本次刚生成的备份

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_ROOT="/root/backups/k8s-netlab-full"
LOCK_FILE="/var/lock/k8s-netlab-backup-full-state.lock"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d-%H%M%S)
FINAL_DEST="$BACKUP_ROOT/$DATE"
STAGING_DEST="$BACKUP_ROOT/.staging-$DATE-$$"

log() {
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
}

mkdir -p "$BACKUP_ROOT"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "[FATAL] 另一个 backup-full-state 任务正在运行，退出"
    exit 1
fi

# 清理上次异常中断（SIGKILL / OOM-kill，EXIT trap 无法捕获）遗留的 staging 残留
# 目录。必须放在拿到 flock 之后才能做：如果放在拿锁之前，一个跑了超过 60 分钟
# 仍在正常工作的备份任务，会被后一次调用在它还没来得及检测到锁被占用之前，把
# 它正在写入的 staging 目录删掉，导致那次备份失败。拿锁之后同一时刻只可能有
# 这一个实例在跑，此时清理的一定是真正的历史残留，不会误删活跃任务。
find "$BACKUP_ROOT" -maxdepth 1 -type d -name ".staging-*" -mmin +60 -exec rm -rf {} + 2>/dev/null || true

cleanup_staging() {
    rm -rf "$STAGING_DEST"
}
trap cleanup_staging EXIT

log "[START] backup-full-state -> $FINAL_DEST"

mkdir -p "$STAGING_DEST"
chmod 700 "$STAGING_DEST"

log "[STEP] data/*.json"
"$PROJECT_ROOT/scripts/backup-data.sh" "$STAGING_DEST"

log "[STEP] Directus postgres + uploads + extensions"
"$PROJECT_ROOT/scripts/backup-directus.sh" "$STAGING_DEST"

log "[STEP] 生成 manifest"
MANIFEST="$STAGING_DEST/manifest.json"
POSTGRES_VERSION="$(docker exec k8s-netlab-postgres postgres --version 2>/dev/null | head -1 || echo unknown)"
RESTORE_CONFIG_FILES=".env.directus（DIRECTUS_DB_PASSWORD/DIRECTUS_SECRET/DIRECTUS_ADMIN_EMAIL/DIRECTUS_ADMIN_PASSWORD），恢复时需从原机器或密钥管理系统另行取得，本备份不包含该文件"

STAGING_DEST="$STAGING_DEST" MANIFEST="$MANIFEST" DATE="$DATE" \
POSTGRES_VERSION="$POSTGRES_VERSION" RESTORE_CONFIG_FILES="$RESTORE_CONFIG_FILES" \
python3 <<'PYEOF'
import hashlib
import json
import os
from datetime import datetime, timezone

staging = os.environ["STAGING_DEST"]
manifest_path = os.environ["MANIFEST"]

files = []
for name in sorted(os.listdir(staging)):
    path = os.path.join(staging, name)
    if not os.path.isfile(path) or name == "manifest.json":
        continue
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    files.append({
        "filename": name,
        "size_bytes": os.path.getsize(path),
        "sha256": h.hexdigest(),
    })

manifest = {
    "backup_id": os.environ["DATE"],
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "postgres_version": os.environ["POSTGRES_VERSION"],
    "restore_config_files_needed": os.environ["RESTORE_CONFIG_FILES"],
    "files": files,
}
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF

log "[STEP] 校验 checksum（promote 前把关）"
STAGING_DEST="$STAGING_DEST" python3 <<'PYEOF'
import hashlib
import json
import os
import sys

staging = os.environ["STAGING_DEST"]
manifest_path = os.path.join(staging, "manifest.json")

with open(manifest_path) as f:
    manifest = json.load(f)

if not manifest["files"]:
    print("[FATAL] manifest 中没有任何文件记录", file=sys.stderr)
    sys.exit(1)

for entry in manifest["files"]:
    path = os.path.join(staging, entry["filename"])
    if entry["size_bytes"] == 0:
        print(f"[FATAL] 空文件: {entry['filename']}", file=sys.stderr)
        sys.exit(1)
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    if h.hexdigest() != entry["sha256"]:
        print(f"[FATAL] checksum 不匹配: {entry['filename']}", file=sys.stderr)
        sys.exit(1)

print(f"[backup-full-state] {len(manifest['files'])} 个文件 checksum 全部通过")
PYEOF

chmod 600 "$STAGING_DEST"/*

log "[STEP] 原子 promote staging -> $FINAL_DEST"
mv "$STAGING_DEST" "$FINAL_DEST"
chmod 700 "$FINAL_DEST"
trap - EXIT

log "[DONE] backup-full-state -> $FINAL_DEST"

# 保留最近 N 天，清理时跳过本次刚生成的备份目录
find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime "+$RETENTION_DAYS" ! -path "$FINAL_DEST" -exec rm -rf {} + 2>/dev/null || true

KEPT=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" | wc -l)
log "[INFO] 当前保留完整备份数量：$KEPT"
