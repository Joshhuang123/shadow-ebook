"""
Owns: SQLite connection + schema + init + first-startup migration + raw query helpers.
Does NOT own: domain logic (books.py owns books CRUD, parent_data.py owns parent data).

Phase 3b 完成: books / parent_data / parent_pin 全部走 SQLite。
首启自动把 data/books/*.json + data/parent/{data.json,pin.hash} 迁进 DB,
原文件备份到 data/{books,parent}.migrated-<ts>/ 留 30 天。
"""
import json
import logging
import shutil
import sqlite3
import threading
import time
from pathlib import Path


logger = logging.getLogger(__name__)


DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
DB_PATH = DATA_DIR / 'shadow.db'
BOOKS_JSON_DIR = DATA_DIR / 'books'


# === SQLite schema ===
# books (Phase 3a): 单内容列 data_json 保留 book/author/description/chapters/cover 全部字段
# parent_data / parent_pin (Phase 3b): 单行表 (id=1),parent_data 存完整 stats/vocab/settings JSON
SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id TEXT PRIMARY KEY,
  data_json TEXT NOT NULL,
  imported_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_updated ON books(updated_at DESC);

CREATE TABLE IF NOT EXISTS parent_data (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  data_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS parent_pin (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  pin_hash TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
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


# === 首次启动:建表 + 一次性 JSON→SQLite 迁移 (per-domain marker) ===
def init_db():
    """幂等。每个域独立检查自己的 migration marker,任何域没迁就迁,跑过就跳过。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()

    # Books migration (Phase 3a)
    if not (DATA_DIR / '.migration_marker').exists():
        _migrate_books_from_json()
        (DATA_DIR / '.migration_marker').write_text(
            f'books migrated at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
            f'原 JSON 备份在 data/books.migrated-<ts>/ (留 30 天,后手动 rm)\n'
        )

    # Parent migration (Phase 3b)
    if not (DATA_DIR / '.parent_migrated').exists():
        _migrate_parent_from_json()
        (DATA_DIR / '.parent_migrated').write_text(
            f'parent data/pin migrated at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
            f'原文件备份在 data/parent.migrated-<ts>/ (留 30 天,后手动 rm)\n'
        )

    # R11: 清理过期备份目录 (>30 天的 books.migrated-* / parent.migrated-*)
    _cleanup_old_migrations(days=30)


def _cleanup_old_migrations(days: int = 30):
    """删 N 天前的 .migrated-* 备份目录。Init 末尾跑,不阻塞首启。"""
    cutoff = time.time() - days * 86400
    removed = 0
    for pattern in ('books.migrated-*', 'parent.migrated-*'):
        for d in DATA_DIR.glob(pattern):
            if not d.is_dir():
                continue
            try:
                # 目录名带 int(time.time()), 直接 parse
                ts_str = d.name.split('.migrated-', 1)[-1]
                ts = int(ts_str)
                if ts < cutoff:
                    shutil.rmtree(d)
                    removed += 1
            except (ValueError, OSError) as e:
                logger.debug(f'跳过 {d}: {e}')
    if removed:
        logger.info(f'清理 {removed} 个过期迁移备份 (>{days} 天)')


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


def _migrate_parent_from_json():
    """首次启动:把 data/parent/data.json + pin.hash 灌进 SQLite,原文件备份到 .migrated-<ts>/。"""
    parent_dir = DATA_DIR / 'parent'
    if not parent_dir.exists():
        return

    data_file = parent_dir / 'data.json'
    pin_file = parent_dir / 'pin.hash'
    if not data_file.exists() and not pin_file.exists():
        return

    backup_dir = DATA_DIR / f'parent.migrated-{int(time.time())}'
    backup_dir.mkdir(exist_ok=True)

    conn = get_db()
    now = int(time.time() * 1000)

    if data_file.exists():
        try:
            data = json.loads(data_file.read_text())
            conn.execute(
                'INSERT OR REPLACE INTO parent_data (id, data_json, updated_at) VALUES (1, ?, ?)',
                (json.dumps(data, ensure_ascii=False), now)
            )
            shutil.move(str(data_file), str(backup_dir / 'data.json'))
            logger.info(f'parent_data 迁移完成, 备份在 {backup_dir.name}/')
        except Exception as e:
            logger.warning(f'parent_data 迁移失败: {e}')

    if pin_file.exists():
        try:
            pin_hash = pin_file.read_text().strip()
            conn.execute(
                'INSERT OR REPLACE INTO parent_pin (id, pin_hash, updated_at) VALUES (1, ?, ?)',
                (pin_hash, now)
            )
            shutil.move(str(pin_file), str(backup_dir / 'pin.hash'))
            logger.info(f'parent_pin 迁移完成, 备份在 {backup_dir.name}/')
        except Exception as e:
            logger.warning(f'parent_pin 迁移失败: {e}')