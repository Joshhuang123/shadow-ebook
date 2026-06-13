"""Round 3 守护: after_request hook 始终发 4 个 security header。

哪一天有人删了 hook 或改了 setdefault 顺序, test 立刻报。
"""
import pytest


@pytest.fixture
def client(tmp_db):
    """用 tmp_db 隔离 DB 后再起 test client (避免污染生产 data/)"""
    import importlib
    from extensions import db
    # 已被 tmp_db fixture monkeypatch, 直接 reload app 让它用新 DB_PATH
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


def test_csp_present(client):
    r = client.get('/api/books')
    csp = r.headers.get('Content-Security-Policy', '')
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_xfo_deny(client):
    r = client.get('/api/books')
    assert r.headers.get('X-Frame-Options') == 'DENY'


def test_nosniff(client):
    r = client.get('/api/books')
    assert r.headers.get('X-Content-Type-Options') == 'nosniff'


def test_referrer_policy(client):
    r = client.get('/api/books')
    assert r.headers.get('Referrer-Policy') == 'same-origin'


def test_headers_on_html_route_too(client):
    """HTML 页面也该有 header, 不只是 /api/* (防 _send_html 漏挂)"""
    r = client.get('/parent')
    assert r.headers.get('X-Frame-Options') == 'DENY'
    assert "default-src 'self'" in r.headers.get('Content-Security-Policy', '')
