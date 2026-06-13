"""家长 PIN: 验默认 0000, 错 PIN 拒绝, 5 次错 lockout, 改 PIN 后旧 PIN 失效。

注意: 实际配置 MAX_ATTEMPTS=5, LOCKOUT_SEC=900 (15 分钟), 不是 plan 写的 60s。
"""
from extensions import parent_data, auth


def test_default_pin_works_on_fresh_db(tmp_db):
    """首启没改过 PIN, 默认 0000 通过, 其它失败"""
    assert parent_data._check_pin('0000') is True
    assert parent_data._check_pin('1234') is False


def test_wrong_pin_rejected(tmp_db):
    parent_data._load_pin_hash()  # 触发默认 PIN 写入
    assert parent_data._check_pin('0001') is False
    assert parent_data._check_pin('') is False
    assert parent_data._check_pin('00000') is False  # 5 位也不匹配 0000


def test_change_pin_invalidates_old(tmp_db):
    """改 PIN 后旧 PIN 立刻失效, 新 PIN 工作"""
    assert parent_data._check_pin('0000') is True
    parent_data._save_pin(parent_data._hash_pin('5678'))
    assert parent_data._check_pin('0000') is False
    assert parent_data._check_pin('5678') is True


def test_login_rate_limit_locks_after_5(tmp_db, clear_login_state):
    """前 5 次都让过 (记录失败), 第 6 次 lockout"""
    ip = '10.0.0.1'
    for i in range(5):
        ok, _ = auth._login_rate_limit_ok(ip)
        assert ok is True, f'第 {i+1} 次该让过'
        auth._login_record_failure(ip)
    ok, retry = auth._login_rate_limit_ok(ip)
    assert ok is False
    assert retry >= 1


def test_login_clear_unblocks(tmp_db, clear_login_state):
    """登录成功 (_login_clear) 后立刻解封, 重新可登录"""
    ip = '10.0.0.2'
    for _ in range(5):
        auth._login_record_failure(ip)
    ok, _ = auth._login_rate_limit_ok(ip)
    assert ok is False
    auth._login_clear(ip)
    ok, _ = auth._login_rate_limit_ok(ip)
    assert ok is True


def test_pin_persists_across_loads(tmp_db):
    """_save_pin → _load_pin_hash 必须读回同一 hash (确认走的是 SQLite 不是内存)"""
    parent_data._save_pin(parent_data._hash_pin('9999'))
    h1 = parent_data._load_pin_hash()
    h2 = parent_data._load_pin_hash()
    assert h1 == h2
    assert h1 == parent_data._hash_pin('9999')


def test_change_pin_rejects_same_value(tmp_db):
    """走 HTTP: 新 PIN == 当前 PIN → 400, 防止前端 bug 重复提交 / 误清限流记录"""
    import importlib, app as app_module
    importlib.reload(app_module)
    client = app_module.app.test_client()
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.post('/api/parent/change-pin', json={'current': '0000', 'new': '0000'})
    assert r.status_code == 400
    assert '不能与当前 PIN 相同' in r.json['error']
    # 验 PIN 真的没变 (退出后 0000 还能登)
    client.post('/api/parent/logout')
    r = client.post('/api/parent/login', json={'pin': '0000'})
    assert r.json['success'] is True


def test_login_returns_remaining_attempts(tmp_db, clear_login_state):
    """登录响应里带 remaining 字段, 失败时递减, 成功时清零 (已登录态)
    注意: 5 次失败后会被锁定, 第 6 次返回 429 而不是 401, 此时 remaining=0"""
    import importlib, app as app_module
    importlib.reload(app_module)
    client = app_module.app.test_client()

    # 第一次错 PIN → remaining 应该是 MAX-1 = 4
    r = client.post('/api/parent/login', json={'pin': '0001'})
    assert r.status_code == 401
    assert r.json.get('remaining') == auth.MAX_ATTEMPTS - 1

    # 第二次错 → remaining = 3
    r = client.post('/api/parent/login', json={'pin': '0002'})
    assert r.json.get('remaining') == auth.MAX_ATTEMPTS - 2

    # 正确 PIN → success (remaining 字段不需要, 已登录态)
    r = client.post('/api/parent/login', json={'pin': '0000'})
    assert r.json['success'] is True
    assert 'remaining' not in r.json or r.json.get('remaining') is None or r.json['remaining'] == 0


def test_login_remaining_zero_when_locked(tmp_db, clear_login_state):
    """5 次失败后被 lock, 第 6 次返回 429 + remaining=0"""
    import importlib, app as app_module
    importlib.reload(app_module)
    client = app_module.app.test_client()
    for _ in range(auth.MAX_ATTEMPTS):
        client.post('/api/parent/login', json={'pin': '0001'})
    r = client.post('/api/parent/login', json={'pin': '0001'})
    assert r.status_code == 429
    assert r.json.get('remaining') == 0
    assert '秒后再试' in r.json['error']
