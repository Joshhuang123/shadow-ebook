"""/api/tts 端点集成测试。

之前只测了内部 _pregen_synthesize, R11 加端到端覆盖:
- cache hit (audio_url 返回)
- 真实合成 (mock edge_tts)
- timeout (mock 挂死)
- 网络失败
- 空文本拒绝
- rate limit
- /api/tts/status 端点 (含 pregenerate 字段)
"""
import importlib
import asyncio
import hashlib
from pathlib import Path

import pytest

from extensions import tts, auth


@pytest.fixture
def client(tmp_db, clear_api_rate, monkeypatch, tmp_path):
    """每个 test 用独立的 TTS_DIR + 重置 _pregen_state"""
    monkeypatch.setattr('extensions.tts.TTS_DIR', tmp_path / 'tts')
    (tmp_path / 'tts').mkdir(parents=True, exist_ok=True)

    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


@pytest.fixture(autouse=True)
def reset_pregen_state():
    tts._pregen_state.update({'running': False, 'attempted': 0, 'succeeded': 0, 'failed': 0, 'last_error': None})
    yield


def _hash(text, voice=tts.DEFAULT_VOICE):
    return hashlib.md5((text + voice).encode()).hexdigest()[:12]


# === cache hit ===
def test_cache_hit_returns_audio_url(client):
    """预先放一个 audio 文件, POST /api/tts 不调 edge_tts, 直接返 audio_url"""
    audio_path = tts.TTS_DIR / f'{_hash("hello world")}.mp3'
    audio_path.write_bytes(b'cached')

    called = []
    class FakeComm:
        def __init__(self, text, voice): called.append((text, voice))
        async def save(self, path): pass
    # 把 import 的 edge_tts.Communicate 替换掉 (top-level import 绑定了名字)
    import extensions.tts as tts_mod
    original = tts_mod.edge_tts.Communicate
    tts_mod.edge_tts.Communicate = FakeComm
    try:
        r = client.post('/api/tts', json={'text': 'hello world'})
        assert r.status_code == 200
        assert r.json['success'] is True
        assert r.json['audio_url'] == f'/audio/tts/{_hash("hello world")}.mp3'
        assert called == [], f'edge_tts 不该被调, 实际调了 {called}'
    finally:
        tts_mod.edge_tts.Communicate = original


# === 真实合成 (mock edge_tts.save 写文件) ===
def test_synthesize_writes_file(client):
    import extensions.tts as tts_mod

    async def fake_save(self, path):
        Path(path).write_bytes(b'fake-mp3-bytes')
    class FakeComm:
        def __init__(self, text, voice): pass
        save = fake_save
    tts_mod.edge_tts.Communicate = FakeComm
    try:
        r = client.post('/api/tts', json={'text': 'unique-text-1'})
        assert r.status_code == 200
        assert r.json['success'] is True
        # 文件真的写了
        audio_path = tts.TTS_DIR / f'{_hash("unique-text-1")}.mp3'
        assert audio_path.exists()
        assert audio_path.read_bytes() == b'fake-mp3-bytes'
    finally:
        tts_mod.edge_tts.Communicate = tts_mod.edge_tts.communicate_orig if hasattr(tts_mod.edge_tts, 'communicate_orig') else tts_mod.edge_tts.Communicate


# === 空文本 ===
def test_empty_text_rejected(client):
    r = client.post('/api/tts', json={'text': ''})
    assert r.status_code == 200  # 业务错误不是 HTTP 错误
    assert r.json['success'] is False
    assert '文本为空' in r.json['error']
    assert r.json['retryable'] is False


# === 缺 text 字段 ===
def test_missing_text_field(client):
    r = client.post('/api/tts', json={})
    assert r.json['success'] is False


# === 网络失败 ===
def test_network_failure_returns_502(client):
    import extensions.tts as tts_mod

    class FakeComm:
        def __init__(self, text, voice): pass
        async def save(self, path):
            raise ConnectionError("edge-tts unreachable")
    original = tts_mod.edge_tts.Communicate
    tts_mod.edge_tts.Communicate = FakeComm
    try:
        r = client.post('/api/tts', json={'text': 'will-fail'})
        assert r.status_code == 502
        assert r.json['success'] is False
        assert r.json['retryable'] is True
        assert r.json['retry_after'] > 0
    finally:
        tts_mod.edge_tts.Communicate = original


# === 超时 ===
def test_timeout_returns_504(client):
    import extensions.tts as tts_mod

    class FakeComm:
        def __init__(self, text, voice): pass
        async def save(self, path):
            await asyncio.sleep(100)  # 远超 15s timeout
    original = tts_mod.edge_tts.Communicate
    tts_mod.edge_tts.Communicate = FakeComm
    try:
        r = client.post('/api/tts', json={'text': 'will-hang'})
        assert r.status_code == 504
        assert r.json['retryable'] is True
        assert '超时' in r.json['error']
    finally:
        tts_mod.edge_tts.Communicate = original


# === 静默失败 (无异常但没写文件) ===
def test_silent_failure_returns_502(client):
    import extensions.tts as tts_mod

    class FakeComm:
        def __init__(self, text, voice): pass
        async def save(self, path):
            pass  # 不抛也不写
    original = tts_mod.edge_tts.Communicate
    tts_mod.edge_tts.Communicate = FakeComm
    try:
        r = client.post('/api/tts', json={'text': 'silent-fail'})
        assert r.status_code == 502
        assert '未返回音频' in r.json['error']
    finally:
        tts_mod.edge_tts.Communicate = original


# === rate limit ===
def test_tts_rate_limit_returns_429(client):
    with auth._API_LOCK:
        auth._API_RATE[('127.0.0.1', 'tts')] = [9999999999.0] * 1000

    r = client.post('/api/tts', json={'text': 'rate-limited'})
    assert r.status_code == 429
    assert r.json['retryable'] is True
    assert r.json['retry_after'] > 0


# === /api/tts/status ===
def test_status_returns_pregenerate_state(client):
    r = client.get('/api/tts/status')
    assert r.status_code == 200
    assert r.json['success'] is True
    assert 'pregenerate' in r.json
    pg = r.json['pregenerate']
    for k in ('running', 'attempted', 'succeeded', 'failed', 'last_error'):
        assert k in pg


def test_status_returns_audio_count(client):
    """audio_files 字段反映 TTS_DIR 中 mp3 数"""
    (tts.TTS_DIR / 'aaa.mp3').write_bytes(b'1')
    (tts.TTS_DIR / 'bbb.mp3').write_bytes(b'1')
    (tts.TTS_DIR / 'ccc.mp3').write_bytes(b'1')
    r = client.get('/api/tts/status')
    assert r.json['audio_files'] == 3


def test_status_rate_limited(client):
    with auth._API_LOCK:
        auth._API_RATE[('127.0.0.1', 'pregenerate')] = [9999999999.0] * 1000
    r = client.get('/api/tts/status')
    assert r.status_code == 429


# === voice 参数生效 ===
def test_custom_voice_creates_distinct_cache(client):
    """同一 text 不同 voice → 不同 hash 文件"""
    import extensions.tts as tts_mod

    async def fake_save(self, path):
        Path(path).write_bytes(b'voice-specific')
    class FakeComm:
        def __init__(self, text, voice): pass
        save = fake_save
    tts_mod.edge_tts.Communicate = FakeComm

    r1 = client.post('/api/tts', json={'text': 'hello', 'voice': 'voice-a'})
    r2 = client.post('/api/tts', json={'text': 'hello', 'voice': 'voice-b'})
    assert r1.json['audio_url'] != r2.json['audio_url']


# === /audio/<path:filename> ===
def test_serve_audio_returns_file(client):
    audio_path = tts.AUDIO_ROOT / 'tts' / 'sample.mp3'
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b'audio-content')

    r = client.get('/audio/tts/sample.mp3')
    assert r.status_code == 200
    assert r.data == b'audio-content'


def test_serve_audio_404_for_missing(client):
    r = client.get('/audio/tts/nonexistent.mp3')
    assert r.status_code == 404