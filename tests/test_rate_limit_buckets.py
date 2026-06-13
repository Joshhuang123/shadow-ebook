"""Round 8 守护: 新加的 pregenerate / export 限流 bucket 真生效.

不需要真发 30 次请求 (TTS 那个的教训), 直接 monkeypatch 限流字典假装已满。
"""
import importlib
import sys
import pytest

from extensions import auth


@pytest.fixture
def client(tmp_db, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


def _fill_rate_limit(bucket, ip='127.0.0.1'):
    """monkeypatch 限流字典: 假装该 IP+bucket 已被打满"""
    with auth._API_LOCK:
        auth._API_RATE[(ip, bucket)] = [9999999999.0] * 1000


# === pregenerate ===

def test_pregenerate_rate_limited(client):
    """pregenerate bucket 满 → 429 + retryable"""
    _fill_rate_limit('pregenerate')
    r = client.post('/api/tts/pregenerate')
    assert r.status_code == 429
    assert r.json['retryable'] is True
    assert r.json['retry_after'] >= 1
    assert '请求过快' in r.json['error']


def test_pregenerate_under_limit_ok(client, tmp_path, monkeypatch):
    """未超限 → 200 + audio_files 计数 (扫 tmp_path 下的 mp3)"""
    monkeypatch.setattr('extensions.tts.TTS_DIR', tmp_path)
    # 放 2 个 mp3 看 count 对不对
    (tmp_path / 'a.mp3').write_bytes(b'x')
    (tmp_path / 'b.mp3').write_bytes(b'x')
    r = client.post('/api/tts/pregenerate')
    assert r.status_code == 200
    assert r.json['audio_files'] == 2


# === export ===

def test_export_rate_limited(client):
    """export bucket 满 → 429 + retryable (不返文件)"""
    client.post('/api/parent/login', json={'pin': '0000'})  # 拿到 auth
    _fill_rate_limit('export')
    r = client.get('/api/parent/export')
    assert r.status_code == 429
    assert r.json['retryable'] is True
    assert '导出请求过快' in r.json['error']


def test_export_under_limit_returns_json(client):
    """未超限 → 返 attachment JSON (Content-Disposition 头在)"""
    client.post('/api/parent/login', json={'pin': '0000'})
    r = client.get('/api/parent/export')
    assert r.status_code == 200
    assert 'attachment' in r.headers.get('Content-Disposition', '')
