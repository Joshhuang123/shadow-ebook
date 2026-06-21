"""db.py init_db + migration 的基础守护。

之前完全没有 db.py 测试, R10 加上确保:
  - init_db 幂等 (跑两次不会炸)
  - 三张表都建出来
  - schema marker 文件被写, 第二次不会重跑 migration
"""
import importlib
import sqlite3

import pytest

from extensions import db


def test_init_db_is_idempotent(tmp_db):
    """init_db 跑两次不报错, 数据保留"""
    db.init_db()
    # 第一次跑后, DB 应该有表
    conn = sqlite3.connect(str(db.DB_PATH))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert 'books' in tables
    assert 'parent_data' in tables
    assert 'parent_pin' in tables

    # 第二次跑不能炸
    db.init_db()


def test_init_db_creates_required_columns(tmp_db):
    """每张表的 schema 必须有正确的列, 防止 init_db 改 schema 时漏测试"""
    conn = sqlite3.connect(str(db.DB_PATH))
    books_cols = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    pin_cols = {r[1] for r in conn.execute("PRAGMA table_info(parent_pin)")}
    pdata_cols = {r[1] for r in conn.execute("PRAGMA table_info(parent_data)")}
    conn.close()

    assert books_cols >= {'id', 'data_json', 'imported_at', 'updated_at'}
    assert pin_cols >= {'id', 'pin_hash', 'updated_at'}
    assert pdata_cols >= {'id', 'data_json', 'updated_at'}


def test_init_db_writes_migration_markers(tmp_db):
    """首跑 init_db 后, 两个 marker 文件都在"""
    # 刚 fixture, tmp_db 已跑过 init_db
    assert (db.DATA_DIR / '.migration_marker').exists()
    assert (db.DATA_DIR / '.parent_migrated').exists()


def test_migrate_books_moves_json_to_db(tmp_db):
    """migrate 逻辑: 在 books/ 放一个 json, 跑 init_db 后进 DB + 文件被备份"""
    books_dir = db.BOOKS_JSON_DIR
    books_dir.mkdir(exist_ok=True)
    sample = {'book': 'Test Book', 'chapters': [{'name': 'C1', 'sentences': ['hi.']}]}
    (books_dir / 'test_book.json').write_text(
        __import__('json').dumps(sample, ensure_ascii=False)
    )

    # 先写 marker 假装 books 还没迁过, 强制 _migrate_books_from_json 重跑
    marker = db.DATA_DIR / '.migration_marker'
    if marker.exists():
        marker.unlink()
    db._migrate_books_from_json()

    # DB 里有这条
    conn = sqlite3.connect(str(db.DB_PATH))
    row = conn.execute("SELECT id FROM books WHERE id = 'test_book'").fetchone()
    conn.close()
    assert row is not None

    # 文件被 move 到 .migrated-* 目录
    assert not (books_dir / 'test_book.json').exists()
    backup_dirs = list(db.DATA_DIR.glob('books.migrated-*'))
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / 'test_book.json').exists()
