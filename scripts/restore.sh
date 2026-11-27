#!/bin/sh
# Restore a PullSpool backup archive produced by scripts/backup.sh.
#
# Usage: bash scripts/restore.sh backups/pullspool-20261126-120000.tar.gz
# The service is stopped, data/db, data/aria2 and data/caddy are replaced, then
# containers are started again. Existing data is moved to a rescue directory.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "用法: bash scripts/restore.sh backups/pullspool-YYYYmmdd-HHMMSS.tar.gz" >&2
    exit 1
fi

if [ -f .env ]; then
    set +u
    . ./.env
    set -u
fi

DATA="${HOST_DATA_DIR:-./data}"
STAMP=$(date +%Y%m%d-%H%M%S)
RESCUE="$DATA/.rescue-$STAMP"

printf '即将用 %s 覆盖 %s 下的数据库与配置。继续？[y/N] ' "$ARCHIVE" "$DATA"
read -r answer
case "$answer" in
    y | Y | yes | YES) ;;
    *) echo "已取消"; exit 1 ;;
esac

echo "停止服务..."
docker compose down --remove-orphans

echo "保存现有数据到 $RESCUE ..."
mkdir -p "$RESCUE"
for item in db aria2 caddy; do
    [ -e "$DATA/$item" ] && mv "$DATA/$item" "$RESCUE/$item"
done
mkdir -p "$DATA/db" "$DATA/aria2" "$DATA/caddy"

echo "解包备份..."
tar xzf "$ARCHIVE" -C "$ROOT"

echo "修复属主..."
if [ -n "${PULLSPOOL_UID:-}" ] && [ "$(id -u)" = "0" ]; then
    chown -R "${PULLSPOOL_UID}:${PULLSPOOL_GID:-$PULLSPOOL_UID}" "$DATA" || true
fi

echo "启动服务..."
docker compose up -d

echo
echo "完成。原数据保留在 $RESCUE（确认无误后可手动删除）。"
echo "建议执行：bash scripts/smoke-test.sh"
