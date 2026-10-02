#!/usr/bin/env bash
# Shadow Ebook - 命令行备份(和家长页的「立即备份」是同一套实现)
#
# 真正干活的代码在 extensions/backup.py,这里只是给终端/CI 用的壳。
# 之前这个脚本自己实现了一遍打包逻辑,于是「页面里备的」和「脚本备的」
# 可能不是一回事 —— 单一实现比两处小心维护更可靠。
#
# 用法:
#   bash scripts/backup.sh
#   BACKUP_DIR=/tmp/backups bash scripts/backup.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
    PY="${ROOT_DIR}/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    echo "[backup] 找不到 python3" >&2
    exit 1
fi

export BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
export DATA_DIR="${DATA_DIR:-${ROOT_DIR}/data}"

exec "${PY}" - <<'PYCODE'
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
from extensions.backup import create_backup, list_backups

data_dir = Path(os.environ['DATA_DIR'])
backup_dir = Path(os.environ['BACKUP_DIR'])

out, removed = create_backup(data_dir, backup_dir)
print(f'[backup] 完成:{out}')
print(f'[backup] 大小:{out.stat().st_size} 字节')
if removed:
    print(f'[backup] 清掉 {len(removed)} 份旧备份:{", ".join(removed)}')
print(f'[backup] 当前共 {len(list_backups(backup_dir))} 份')
PYCODE
