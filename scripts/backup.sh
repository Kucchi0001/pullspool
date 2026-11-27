#!/bin/sh
# Back up the SQLite database (consistent snapshot), aria2 session and config.
# Downloads are NOT included by default; pass --with-files to include them.
#
# Usage: bash scripts/backup.sh [--with-files]
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ -f .env ]; then
    set +u
    . ./.env
    set -u
fi

DATA="${HOST_DATA_DIR:-./data}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP=$(date +%Y%m%d-%H%M%S)
WITH_FILES=0
[ "${1:-}" = "--with-files" ] && WITH_FILES=1

mkdir -p "$BACKUP_DIR"
mkdir -p "$DATA/db/backups"

echo "== 备份 PullSpool =="
echo "数据目录: $DATA"
echo "备份目录: $BACKUP_DIR"

docker_ok=0
if docker compose ps --status running backend 2>/dev/null | grep -q backend; then
    docker_ok=1
fi

if [ "$docker_ok" -eq 1 ]; then
    echo "使用容器内 SQLite 在线备份（一致性快照）..."
    docker compose exec -T backend python - "$STAMP" <<'PY'
import sqlite3
import sys

stamp = sys.argv[1]
source = sqlite3.connect("/data/db/pullspool.db")
target = sqlite3.connect(f"/data/db/backups/pre-backup-{stamp}.db")
source.backup(target)
target.close()
source.close()
print(f"/data/db/backups/pre-backup-{stamp}.db")
PY
else
    echo "[warn] backend 未运行，直接复制数据库文件（请确保服务已停止，否则可能不一致）"
    cp -a "$DATA/db/pullspool.db" "$DATA/db/backups/pre-backup-$STAMP.db" 2>/dev/null || true
fi

tar_args=""
if [ "$WITH_FILES" -eq 1 ]; then
    echo "包含下载文件（体积可能很大）..."
    tar_args="$DATA"
else
    tar_args="$DATA/db $DATA/aria2 $DATA/caddy"
fi

ARCHIVE="$BACKUP_DIR/pullspool-$STAMP.tar.gz"
# shellcheck disable=SC2086
tar czf "$ARCHIVE" -C "$ROOT" $tar_args
cp .env "$BACKUP_DIR/pullspool-$STAMP.env" 2>/dev/null || true
chmod 600 "$BACKUP_DIR/pullspool-$STAMP.env" 2>/dev/null || true

# Keep the 7 most recent archives.
ls -1t "$BACKUP_DIR"/pullspool-*.tar.gz 2>/dev/null | sed -n '8,$p' | while read -r old; do
    rm -f "$old"
done

echo
echo "完成：$ARCHIVE"
echo "配置副本：$BACKUP_DIR/pullspool-$STAMP.env（包含密钥，注意保管）"
echo "恢复：bash scripts/restore.sh $ARCHIVE"
