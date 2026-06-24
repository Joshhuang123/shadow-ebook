"""家长鉴权流程端到端测试。

覆盖: login / logout / change-pin / check / export / reset。
之前 0 覆盖, R11 加测试钉住 PIN 流 + rate limit + 401 401 401 流程。
"""
import importlib
import json

import pytest

from extensions import parent_data


@pytest.fixture
def client(tmp_db, clear_login_state, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


# === /api/parent/check ===
def test_check_unauthenticated(client):
    r = client.get('/api/parent/check')
    assert r.status_code == 200
    assert r.json == {"authenticated": False}


def test_check_after_login(client):
    # 默认 PIN 是 0000
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.get('/api/parent/check')
    assert r.json == {"authenticated": True}


# === /api/parent/login ===
def test_login_success_default_pin(client):
    r = client.post('/api/parent/login', json={'pin': '0000'})
    assert r.status_code == 200
    assert r.json['success'] is True


def test_login_wrong_pin_returns_remaining(client):
    r = client.post('/api/parent/login', json={'pin': '1234'})
    assert r.status_code == 401
    assert r.json['success'] is False
    assert 'PIN 错误' in r.json['error']
    # 4 次剩余 (默认 5 次 - 1 次错)
    assert r.json['remaining'] == 4


def test_login_non_digit_pin_rejected(client):
    """非数字 PIN 应该是 400 + 计入失败 (防 'abcd' 触发 _verify_pin 不必要的 scrypt 计算)"""
    r = client.post('/api/parent/login', json={'pin': 'abcd'})
    assert r.status_code == 400
    assert r.json['remaining'] == 4


def test_login_rate_limit_locks_after_5_fails(client):
    """5 次失败后第 6 次返回 429"""
    for _ in range(5):
        client.post('/api/parent/login', json={'pin': '9999'})
    r = client.post('/api/parent/login', json={'pin': '0000'})  # 即使对 PIN 也被锁
    assert r.status_code == 429
    assert '尝试次数过多' in r.json['error']
    assert r.json['remaining'] == 0


def test_login_success_clears_window(client):
    """成功登录清掉 _LOGIN_WINDOW, 不会留下之前失败计数"""
    for _ in range(3):
        client.post('/api/parent/login', json={'pin': '9999'})
    client.post('/api/parent/login', json={'pin': '0000'})  # 成功
    # 现在又可以失败 5 次
    for _ in range(5):
        r = client.post('/api/parent/login', json={'pin': '9999'})
        assert r.status_code == 401


# === /api/parent/logout ===
def test_logout_requires_auth(client):
    r = client.post('/api/parent/logout')
    assert r.status_code == 401


def test_logout_clears_session(client):
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.post('/api/parent/logout')
    assert r.status_code == 200
    r = client.get('/api/parent/check')
    assert r.json == {"authenticated": False}


# === /api/parent/change-pin ===
def test_change_pin_requires_auth(client):
    r = client.post('/api/parent/change-pin', json={'current': '0000', 'new': '1234'})
    assert r.status_code == 401


def test_change_pin_success(client):
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.post('/api/parent/change-pin', json={'current': '0000', 'new': '1234'})
    assert r.json['success'] is True
    # 旧 PIN 失效
    r = client.post('/api/parent/change-pin', json={'current': '0000', 'new': '5678'})
    assert r.status_code == 401
    # 新 PIN 可用 (logout + login)
    client.post('/api/parent/logout')
    r = client.post('/api/parent/login', json={'pin': '1234'})
    assert r.json['success'] is True


def test_change_pin_same_value_rejected(client):
    """新 PIN 与当前 PIN 相同 → 400 (防止误操作或前端 bug)"""
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.post('/api/parent/change-pin', json={'current': '0000', 'new': '0000'})
    assert r.status_code == 400
    assert '相同' in r.json['error']


def test_change_pin_non_digit_rejected(client):
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.post('/api/parent/change-pin', json={'current': '0000', 'new': 'abcd'})
    assert r.status_code == 400


def test_change_pin_wrong_current_rejected(client):
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.post('/api/parent/change-pin', json={'current': '9999', 'new': '1234'})
    assert r.status_code == 401


# === /api/parent/data GET ===
def test_get_data_requires_auth(client):
    r = client.get('/api/parent/data')
    assert r.status_code == 401


def test_get_data_returns_default_shape(client):
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.get('/api/parent/data')
    assert r.json['success'] is True
    assert set(r.json['data'].keys()) >= {'stats', 'vocabulary', 'settings'}


# === /api/parent/export ===
def test_export_requires_auth(client):
    r = client.get('/api/parent/export')
    assert r.status_code == 401


def test_export_returns_json_attachment(client):
    client.post('/api/parent/login', json={'pin': '0000'})
    # 先 POST 一些数据再导出
    client.post('/api/parent/data', json={'stats': {'todayMinutes': 15}})
    r = client.get('/api/parent/export')
    assert r.status_code == 200
    assert 'attachment' in r.headers['Content-Disposition']
    payload = json.loads(r.data)
    assert payload.get('stats', {}).get('todayMinutes') == 15


# === /api/parent/reset ===
def test_reset_requires_auth(client):
    r = client.post('/api/parent/reset')
    assert r.status_code == 401


def test_reset_clears_data(client):
    client.post('/api/parent/login', json={'pin': '0000'})
    client.post('/api/parent/data', json={'stats': {'todayMinutes': 99}})
    r = client.post('/api/parent/reset')
    assert r.json['success'] is True
    r = client.get('/api/parent/data')
    assert r.json['data']['stats'] == {}