"""anon 上报端点 (/api/parent/data POST) 的测试。

anon 端点接受孩子的 stats/vocab/settings 上报, 不需要鉴权。
合并写入, 不会覆盖整张表 — 关键不变量。
"""
import importlib

import pytest


@pytest.fixture
def client(tmp_db, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


def _read_parent_data_json() -> dict:
    """读装配后的完整 parent data。

    R22 拆表后数据不再有单行 JSON, 但本文件测的是合并语义 ( anon 上报
    进不进得去、会不会互相覆盖 ), 走 _load_parent_data 的装配视图即可,
    和家长页 GET /api/parent/data 看到的是同一份。
    """
    from extensions import parent_data
    return parent_data._load_parent_data()


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
