"""守护: /api/debug/* 端点默认不可达。

背景: 这个端点原本"不需鉴权 + 30/min 限流",LAN 上任何设备(平板、访客手机)
都能拉到全部书籍的解析统计。现在默认 404,只有 SHADOW_DEBUG 显式打开才放行,
且仍要家长鉴权。

特别守护 SHADOW_DEBUG=0 这个 case: 写成 `if os.environ.get('SHADOW_DEBUG')`
的话,'0' 是非空字符串 → truthy → debug 反而被打开。这条测试就是防这个回归。
"""
import importlib

import pytest


AUDIT_URL = '/api/debug/book/any_book_id/audit'


def _client(monkeypatch, debug_value):
    """按指定 env 值造一个 test client(不 reload 也能生效 —— gate 在请求时读 env,
    但 reload 顺带让 tmp_db fixture 的 DB_PATH monkeypatch 生效)。"""
    if debug_value is None:
        monkeypatch.delenv('SHADOW_DEBUG', raising=False)
    else:
        monkeypatch.setenv('SHADOW_DEBUG', debug_value)
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


@pytest.mark.parametrize('value', [None, '', '0', 'false', 'FALSE', 'no', 'off', ' 0 '])
def test_audit_404_when_debug_off(tmp_db, monkeypatch, value):
    """这些值一律算关闭。"""
    r = _client(monkeypatch, value).get(AUDIT_URL)
    assert r.status_code == 404
    assert 'issues_by_chapter' not in r.get_data(as_text=True)


@pytest.mark.parametrize('value', ['1', 'true', 'yes', 'on'])
def test_audit_requires_parent_auth_when_debug_on(tmp_db, monkeypatch, value):
    """开了还不够 —— 必须是已登录家长,否则 401。"""
    r = _client(monkeypatch, value).get(AUDIT_URL)
    assert r.status_code == 401
    # jsonify 默认 ensure_ascii,中文是 \uXXXX 转义的,必须 get_json() 解码后比
    assert r.get_json().get('error') == '未授权'


def test_audit_body_never_leaks_stats_when_denied(tmp_db, monkeypatch):
    """拒绝时响应体不能带任何解析统计字段(防止 404 页面顺手把数据吐出来)。"""
    for value in (None, '0', '1'):
        body = _client(monkeypatch, value).get(AUDIT_URL).get_data(as_text=True)
        assert 'issues_by_chapter' not in body
        assert 'total_sentences' not in body
