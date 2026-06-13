"""
Owns: SQLite connection + schema + init + first-startup migration + raw query helpers.
Does NOT own: domain logic (books.py owns books CRUD, parent_data.py owns parent data).

Phase 3a status:
- books 表迁完,parent_data / parent_pin 还在 JSON (后续 phase 迁)
- `_safe_write_json` 留作 parent_data 写 JSON 用
"""
import json
import logging
import os
import secrets
import shutil
import sqlite3
import threading
import time
from pathlib import Path


logger = logging.getLogger(__name__)


DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
DB_PATH = DATA_DIR / 'shadow.db'
BOOKS_JSON_DIR = DATA_DIR / 'books'


# === SQLite schema (books 表 — Phase 3a) ===
# 只存 data_json 一个内容字段,保留原 JSON 全部字段 (book/author/description/chapters/cover)
# 不单独列 title/chapters_json 是为了: 1) 保留 author/description 2) 简化 schema 3) 8 本书的体量不值得拆列
SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id TEXT PRIMARY KEY,
  data_json TEXT NOT NULL,
  imported_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_updated ON books(updated_at DESC);
"""


# === thread-local connection ===
_local = threading.local()


def get_db():
    """返回 thread-local SQLite 连接 (WAL 模式,支持并发读)。"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), isolation_level=None)  # autocommit
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute('PRAGMA journal_mode=WAL')
        _local.conn.execute('PRAGMA foreign_keys=ON')
    return _local.conn


# === 共享文件 utility (parent_data.py 还用,Phase 3b 删) ===
def _safe_write_json(path: Path, data):
    """原子写 JSON: 写 .tmp + fsync + rename, 防止并发写半截 / 崩溃残留。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f'.tmp.{os.getpid()}.{secrets.token_hex(4)}')
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try: tmp_path.unlink()
        except OSError: pass
        raise


# === 首次启动:建表 + 一次性 JSON→SQLite 迁移 ===
def init_db():
    """幂等。首次启动建表 + 扫 data/books/*.json 灌进 SQLite,后续调用无副作用。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    is_fresh = not DB_PATH.exists()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()

    if is_fresh:
        marker = DATA_DIR / '.migration_marker'
        if not marker.exists():
            _migrate_books_from_json()
            marker.write_text(
                f'books migrated at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
                f'原 JSON 备份在 data/books.migrated-<ts>/ (留 30 天,后手动 rm)\n'
            )


def _migrate_books_from_json():
    """首次启动:把 data/books/*.json 灌进 SQLite,原文件移到 .migrated-<ts>/ 留底。"""
    if not BOOKS_JSON_DIR.exists():
        return

    json_files = list(BOOKS_JSON_DIR.glob('*.json'))
    if not json_files:
        return

    backup_dir = DATA_DIR / f'books.migrated-{int(time.time())}'
    backup_dir.mkdir(exist_ok=True)

    conn = get_db()
    now = int(time.time() * 1000)
    migrated = 0
    failed = 0
    for f in json_files:
        try:
            data = json.loads(f.read_text())
            book_id = f.stem
            data_json = json.dumps(data, ensure_ascii=False)
            conn.execute(
                'INSERT OR REPLACE INTO books (id, data_json, imported_at, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (book_id, data_json, now, now)
            )
            shutil.move(str(f), str(backup_dir / f.name))
            migrated += 1
        except Exception as e:
            logger.warning(f'迁移 {f.name} 失败: {e}')
            failed += 1

    logger.info(f'books 迁移完成: {migrated} 成功, {failed} 失败, 备份在 {backup_dir.name}/')


def register_routes(app):
    """db 模块没有 HTTP 路由,只被其他模块 import 使用。"""
    pass