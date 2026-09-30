#!/usr/bin/env bash
# Shadow Ebook - data/ 备份脚本
# 用法:
#   bash scripts/backup.sh                  # 默认备份到 backups/,留 14 天
#   BACKUP_KEEP_DAYS=30 bash scripts/backup.sh
#   BACKUP_DIR=/tmp/backups bash scripts/backup.sh
#   DATA_DIR=/tmp/fakedata bash scripts/backup.sh   # 备份别处(测试用)
#
# 推荐:加 cron 每日凌晨跑
#   0 3 * * * cd /path/to/shadow-learning && bash scripts/backup.sh >> logs/backup.log 2>&1

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${DATA_DIR:-${ROOT_DIR}/data}"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/shadow-data-${TS}.tar.gz"

if [[ ! -d "${DATA_DIR}" ]]; then
    echo "[backup] data/ 不存在,跳过(${DATA_DIR})"
    exit 0
fi

mkdir -p "${BACKUP_DIR}"

# --- 先把 SQLite 拍成一致的快照,再打包 ---
#
# 为什么必须先快照(2026-09-30 修):app 用 WAL 模式(db.py 里
# PRAGMA journal_mode=WAL),已提交的写入先落在 shadow.db-wal,等 checkpoint
# 才并进 shadow.db。所以「只打包 shadow.db、把 -wal 排除掉」丢的正是最新
# 的数据 —— 排除 WAL 不是避免不一致,而是制造静默丢失。
# 实测:写入一条记录后只 cp shadow.db,查那条记录 = 找不到。
#
# sqlite3 的 .backup 是在线快照,app 照常跑着也能拿到一致的单文件副本。
DATA_PARENT="$(cd "${DATA_DIR}/.." && pwd)"
DATA_NAME="$(basename "${DATA_DIR}")"

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT
mkdir -p "${STAGE}/${DATA_NAME}"

if [[ -f "${DATA_DIR}/shadow.db" ]]; then
    sqlite3 "${DATA_DIR}/shadow.db" ".backup '${STAGE}/${DATA_NAME}/shadow.db'"
    echo "[backup] SQLite 快照完成"
else
    echo "[backup] 还没有 shadow.db,跳过数据库快照"
fi

# 其余文件(books/covers/parent/grammar)不是 SQLite,直接拷就是一致的。
# .secret 不进备份:它是 0600 的本地签名密钥,换机器时 app 会自己重新生成。
# shadow.log 也不进:可再生,而且它比数据库大得多。
tar -cf - -C "${DATA_PARENT}" \
    --exclude="${DATA_NAME}/.secret" \
    --exclude="${DATA_NAME}/shadow.db" \
    --exclude="${DATA_NAME}/shadow.db-wal" \
    --exclude="${DATA_NAME}/shadow.db-shm" \
    --exclude="${DATA_NAME}/shadow.log" \
    "${DATA_NAME}/" | tar -xf - -C "${STAGE}"

echo "[backup] 打包 ${STAGE}/${DATA_NAME} → ${OUT}"
tar -czf "${OUT}" -C "${STAGE}" "${DATA_NAME}"

# 删除过期备份
find "${BACKUP_DIR}" -name 'shadow-data-*.tar.gz' -mtime "+${KEEP_DAYS}" -delete

echo "[backup] 完成:"
echo "  最新: ${OUT}"
echo "  大小: $(du -h "${OUT}" | cut -f1)"
echo "  保留: ${KEEP_DAYS} 天"
echo "  当前数量: $(ls "${BACKUP_DIR}"/shadow-data-*.tar.gz 2>/dev/null | wc -l | tr -d ' ')"