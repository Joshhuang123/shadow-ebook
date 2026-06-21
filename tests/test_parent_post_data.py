"""anon 上报端点 (/api/parent/data POST) 的测试。

anon 端点接受孩子的 stats/vocab/settings 上报, 不需要鉴权。
合并写入, 不会覆盖整张表 — 关键不变量。
"""
import importlib
import json
import sqlite3

import pytest

from extensions import db as db_module


@pytest.fixture
def client(tmp_db, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


def _read_parent_data_json() -> dict:
    """从 monkeypatch 后的 DB_PATH 读 — 别在模块顶层 import DB_PATH, fixture 改不到。"""
    conn = sqlite3.connect(str(db_module.DB_PATH))
    row = conn.execute("SELECT data_json FROM parent_data WHERE id = 1").fetchone()
    conn.close()
    return json.loads(row[0]) if row else {}


def test_post_data_does_not_require_auth(client):
    """anon 孩子端能直接 POST, 不需要先登录"""
    r = client.post('/api/parent/data', json={'stats': {'todayMinutes': 15}})
    assert r.status_code == 200
    assert r.json['success'] is True


def test_post_data_merges_stats(client):
    """多次 POST stats 合并, 不会清掉前一次的"""
    client.post('/api/parent/data', json={'stats': {'a': 1}})
    client.post('/api/parent/data', json={'stats': {'b': 2}})
    data = _read_parent_data_json()
    assert data['stats'].get('a') == 1
    assert data['stats'].get('b') == 2


def test_post_data_merges_vocabulary(client):
    """vocabulary.lookedWords 字典合并, 已有 key 不被覆盖"""
    client.post('/api/parent/data', json={'vocabulary': {'lookedWords': {'hello': True}}})
    client.post('/api/parent/data', json={'vocabulary': {'lookedWords': {'world': True}}})
    data = _read_parent_data_json()
    assert data['vocabulary']['lookedWords']['hello'] is True
    assert data['vocabulary']['lookedWords']['world'] is True


def test_post_data_ignores_unknown_sections(client):
    """payload 里多塞的 section (e.g. 'hacker_key') 不该进 DB"""
    client.post('/api/parent/data', json={'stats': {'a': 1}, 'evil_section': {'x': 1}})
    data = _read_parent_data_json()
    assert 'evil_section' not in data, '未知 section 不该被写入'
    assert data['stats'].get('a') == 1


def test_post_data_empty_payload_is_noop(client):
    """payload = {} 也不报错, 啥都不改"""
    r = client.post('/api/parent/data', json={})
    assert r.status_code == 200
    assert r.json['success'] is True


def test_post_data_rejects_non_dict_sections(client):
    """payload 里 section 不是 dict (e.g. 数组) → 忽略该 section, 不崩"""
    r = client.post('/api/parent/data', json={'stats': 'not a dict'})
    assert r.status_code == 200
    assert r.json['success'] is True
    # stats 不该被错误写入
    data = _read_parent_data_json()
    assert 'stats' not in data or data['stats'] == {}


def test_post_data_is_rate_limited(client):
    """sync bucket 满 → 429。直接打 sync 桶。"""
    from extensions import auth
    with auth._API_LOCK:
        auth._API_RATE[('127.0.0.1', 'sync')] = [9999999999.0] * 1000

    r = client.post('/api/parent/data', json={'stats': {'a': 1}})
    assert r.status_code == 429
    assert '上报过快' in r.json['error']


def test_post_data_preserves_existing_keys_in_section(client):
    """同 section 的 POST 不会清掉其他 key (新值合并进旧 dict)"""
    client.post('/api/parent/data', json={'settings': {'fontSize': 16, 'theme': 'day'}})
    client.post('/api/parent/data', json={'settings': {'fontSize': 20}})  # 只更新 fontSize
    data = _read_parent_data_json()
    assert data['settings']['fontSize'] == 20
    assert data['settings']['theme'] == 'day', 'theme 不该被这次 POST 清掉'
