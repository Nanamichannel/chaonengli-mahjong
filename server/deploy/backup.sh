#!/usr/bin/env bash
# 天马麻将 数据库备份（SQLite 在 WAL 模式下**不能直接 cp**，必须用 .backup）
#
# 装到 cron：
#   sudo crontab -e
#   0 4 * * * /opt/tianma/server/deploy/backup.sh >> /var/log/tianma-backup.log 2>&1
#
# 默认保留最近 14 天。
set -euo pipefail

SRC_DIR=/opt/tianma/server/data
DST_DIR=/opt/tianma/backup
KEEP_DAYS=14
STAMP=$(date +%F_%H%M)

mkdir -p "$DST_DIR"
command -v sqlite3 >/dev/null || { echo "缺 sqlite3：apt install -y sqlite3"; exit 1; }

n=0
for db in "$SRC_DIR"/*.db; do
  [ -e "$db" ] || continue
  name=$(basename "$db" .db)
  out="$DST_DIR/${name}_${STAMP}.db"
  sqlite3 "$db" ".backup '$out'"        # 一致性快照，正在写也安全
  gzip -f "$out"
  n=$((n + 1))
done

# 老备份清理
find "$DST_DIR" -name '*.db.gz' -mtime "+$KEEP_DAYS" -delete 2>/dev/null || true

echo "[$(date '+%F %T')] 备份 $n 个库 → $DST_DIR（保留 ${KEEP_DAYS} 天）"
