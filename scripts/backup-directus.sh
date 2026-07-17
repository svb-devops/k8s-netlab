#!/usr/bin/env bash
# backup-directus.sh — 备份 Directus PostgreSQL（pg_dump custom format）+ uploads + extensions
#
# 用法：backup-directus.sh <DEST_DIR>（DEST_DIR 须已存在，由调用方创建并负责后续 promote）
#
# 产出（写入 DEST_DIR）：
#   directus_postgres.dump    pg_dump -Fc（custom format，可用 pg_restore 恢复）
#   directus_uploads.tar.gz   data/directus/uploads 归档
#   directus_extensions.tar.gz  data/directus/extensions 归档
#
# 不做的事：不备份 .env / .env.directus，不在日志中输出数据库密码或其它 secret。
# 任一步骤失败立即以非零退出，不留半成品文件。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:?用法: backup-directus.sh <DEST_DIR>}"
CONTAINER="k8s-netlab-postgres"
DB_NAME="directus"
DB_USER="directus"
ENV_FILE="$PROJECT_ROOT/.env.directus"

if [ ! -d "$DEST" ]; then
    echo "[backup-directus] [FATAL] 目标目录不存在: $DEST" >&2
    exit 1
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "[backup-directus] [FATAL] 容器 $CONTAINER 不存在或未运行" >&2
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "[backup-directus] [FATAL] 未找到 $ENV_FILE" >&2
    exit 1
fi

DIRECTUS_DB_PASSWORD="$(grep -m1 '^DIRECTUS_DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
if [ -z "$DIRECTUS_DB_PASSWORD" ]; then
    echo "[backup-directus] [FATAL] $ENV_FILE 中未配置 DIRECTUS_DB_PASSWORD" >&2
    exit 1
fi

echo "[backup-directus] pg_dump ${DB_NAME}（custom format）"
DUMP_FILE="$DEST/directus_postgres.dump"
# 密码通过 stdin 传给容器内的 sh，不作为 `docker exec` 的 argv 参数——argv 经
# `ps auxww` / `/proc/<pid>/cmdline` 对本机其它用户可见，而 stdin 管道不会出现在
# 进程列表里。`printf`/`docker exec -i sh -c '...'` 之间没有第三方进程会把密码
# 暴露成命令行参数。
if ! printf '%s' "$DIRECTUS_DB_PASSWORD" | docker exec -i "$CONTAINER" sh -c '
    PGPASSWORD="$(cat)"
    export PGPASSWORD
    exec pg_dump -U "$1" -d "$2" -Fc
' _ "$DB_USER" "$DB_NAME" >"$DUMP_FILE" 2>"$DEST/.pg_dump.stderr"; then
    echo "[backup-directus] [FATAL] pg_dump 失败" >&2
    cat "$DEST/.pg_dump.stderr" >&2
    rm -f "$DUMP_FILE" "$DEST/.pg_dump.stderr"
    exit 1
fi
rm -f "$DEST/.pg_dump.stderr"

if [ ! -s "$DUMP_FILE" ]; then
    echo "[backup-directus] [FATAL] pg_dump 产出文件为空: $DUMP_FILE" >&2
    exit 1
fi

echo "[backup-directus] 归档 uploads/"
UPLOADS_DIR="$PROJECT_ROOT/data/directus/uploads"
if [ ! -d "$UPLOADS_DIR" ]; then
    echo "[backup-directus] [FATAL] uploads 目录不存在: $UPLOADS_DIR" >&2
    exit 1
fi
tar czf "$DEST/directus_uploads.tar.gz" -C "$PROJECT_ROOT/data/directus" uploads

echo "[backup-directus] 归档 extensions/"
EXT_DIR="$PROJECT_ROOT/data/directus/extensions"
if [ ! -d "$EXT_DIR" ]; then
    echo "[backup-directus] [FATAL] extensions 目录不存在: $EXT_DIR" >&2
    exit 1
fi
tar czf "$DEST/directus_extensions.tar.gz" -C "$PROJECT_ROOT/data/directus" extensions

echo "[backup-directus] 完成：$(basename "$DUMP_FILE"), directus_uploads.tar.gz, directus_extensions.tar.gz"
