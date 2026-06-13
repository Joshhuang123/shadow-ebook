"""共享 fixture: tmp_db 隔离 DB 状态, clear_login_state 隔离登录限流字典。

测试一定要用 tmp_db,避免误写 data/shadow.db。
"""
import sys
from pathlib import Path

import pytest

# 让 `from extensions.xxx import ...` 工作 (tests/ 不在 sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import db, auth


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """孤立的 SQLite DB,跑完自动清,不污染生产 data/shadow.db。

    关键: 必须重置 thread-local conn,否则 get_db() 会用上一次的连接,
    哪怕 monkeypatch 把 DB_PATH 改了也不会重新打开新文件。
    """
    test_data = tmp_path / 'data'
    test_data.mkdir()
    monkeypatch.setattr(db, 'DATA_DIR', test_data)
    monkeypatch.setattr(db, 'DB_PATH', test_data / 'shadow.db')
    monkeypatch.setattr(db, 'BOOKS_JSON_DIR', test_data / 'books')

    if hasattr(db._local, 'conn') and db._local.conn:
        try: db._local.conn.close()
        except Exception: pass
        db._local.conn = None

    db.init_db()
    yield test_data

    if hasattr(db._local, 'conn') and db._local.conn:
        try: db._local.conn.close()
        except Exception: pass
        db._local.conn = None


@pytest.fixture
def clear_login_state():
    """跑前/跑后都清 _LOGIN_WINDOW,免得测试相互污染。"""
    with auth._AUTH_LOCK:
        auth._LOGIN_WINDOW.clear()
    yield
    with auth._AUTH_LOCK:
        auth._LOGIN_WINDOW.clear()


@pytest.fixture
def clear_api_rate():
    """跑前/跑后都清 _API_RATE (TTS/sync/import/global 限流),免得测试间相互污染。

    不清的话: 上一组 TTS 限流测试跑满 30/min, 下一组立刻 429。
    """
    with auth._API_LOCK:
        auth._API_RATE.clear()
    yield
    with auth._API_LOCK:
        auth._API_RATE.clear()
