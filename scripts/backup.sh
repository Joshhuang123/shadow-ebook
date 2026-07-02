#!/usr/bin/env bash
# Shadow Ebook - data/ 备份脚本
# 用法:
#   bash scripts/backup.sh                  # 默认备份到 backups/,留 14 天
#   BACKUP_KEEP_DAYS=30 bash scripts/backup.sh
#   BACKUP_DIR=/tmp/backups bash scripts/backup.sh
#
# 推荐:加 cron 每日凌晨跑
#   0 3 * * * cd /path/to/shadow-learning && bash scripts/backup.sh >> logs/backup.log 2>&1

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/shadow-data-${TS}.tar.gz"

if [[ ! -d "${DATA_DIR}" ]]; then
    echo "[backup] data/ 不存在,跳过(${DATA_DIR})"
    exit 0
fi

mkdir -p "${BACKUP_DIR}"

echo "[backup] 打包 ${DATA_DIR} → ${OUT}"
# --exclude 跳过运行时产物(.secret 用 0600,丢不了;但 SQLite WAL 日志可能正在写,排除避免不一致)
tar --exclude='data/.secret' \
    --exclude='data/shadow.db-wal' \
    --exclude='data/shadow.db-shm' \
    -czf "${OUT}" -C "${ROOT_DIR}" data/

# 删除过期备份
find "${BACKUP_DIR}" -name 'shadow-data-*.tar.gz' -mtime "+${KEEP_DAYS}" -delete

echo "[backup] 完成:"
echo "  最新: ${OUT}"
echo "  大小: $(du -h "${OUT}" | cut -f1)"
echo "  保留: ${KEEP_DAYS} 天"
echo "  当前数量: $(ls "${BACKUP_DIR}"/shadow-data-*.tar.gz 2>/dev/null | wc -l | tr -d ' ')"