"""Round 7 守护: /api/tts 失败路径返回 retryable + retry_after, 不泄露原始异常.

三种失败都要测:
  - 超时 (asyncio.TimeoutError): 504 + retryable + retry_after
  - edge_tts 抛异常: 502 + retryable + retry_after + 不含原始异常字符串
  - 静默失败 (没抛也没文件): 502 + retryable

注意: 每次用唯一 text 避免命中上轮测试的 TTS 缓存 (md5(text+voice) 决定文件名)。
R10: 改用 monkeypatch.setattr 注入 fake Communicate — 之前用 patch.dict(sys.modules)
不再有效, 因为 tts.py 现在是模块顶部 import edge_tts (而不是函数内 import), 那时
extensions.tts.edge_tts 已经绑死到原 module, 之后改 sys.modules 不影响。
"""
import asyncio
import importlib
import uuid

import pytest


@pytest.fixture
def client(tmp_db, clear_api_rate, tmp_path):
    """tmp_db 隔离 DB; clear_api_rate 清 TTS/sync 限流; reload app 让 module-level 状态干净

    还 monkeypatch TTS_DIR 到 tmp_path, 免得真跑出 mp3 污染生产 audio/tts 目录
    (也避免本测试的 mp3 残留影响其他测试)。
    """
    import app as app_module
    importlib.reload(app_module)
    fake_tts = tmp_path / 'tts'
    fake_tts.mkdir()
    monkeypatch_tts = pytest.MonkeyPatch()
    monkeypatch_tts.setattr('extensions.tts.TTS_DIR', fake_tts)
    yield app_module.app.test_client()
    monkeypatch_tts.undo()


def _post_tts(client, text=None):
    return client.post('/api/tts', json={
        'text': text or f'unique-{uuid.uuid4()}',
        'voice': 'en-US-AriaNeural',
    })


def _patch_communicate(monkeypatch, fake_cls):
    """注入 fake Communicate 到 extensions.tts.edge_tts (已经是 top-level import, 绑定后不变)"""
    monkeypatch.setattr('extensions.tts.edge_tts.Communicate', fake_cls)


# === 基础错误: 用户输入 (不用 mock edge_tts) ===

def test_tts_empty_text_not_retryable(client):
    """空文本是用户输入问题, retryable 必须 False"""
    r = client.post('/api/tts', json={'text': '', 'voice': 'en-US-AriaNeural'})
    assert r.status_code == 200  # 注: 当前实现用 200 + success:false, 跟其他一致
    assert r.json['success'] is False
    assert r.json['retryable'] is False


def test_tts_rate_limit_returns_retryable(client):
    """429 也带 retryable + retry_after, 前端能自动 backoff

    避开真跑 30 次 edge_tts (58s), 直接 monkeypatch 限流字典假装已满。
    """
    from extensions import auth
    with auth._API_LOCK:
        now = 9999999999.0  # 远离真实时间, 不会被 _api_rate_limit_ok 内的 now 过滤掉
        auth._API_RATE[('127.0.0.1', 'tts')] = [now] * 30
    r = _post_tts(client)
    assert r.status_code == 429
    assert r.json['retryable'] is True
    assert r.json['retry_after'] >= 1


# === edge_tts 抛异常 ===

def test_tts_exception_returns_502_with_retryable(client, monkeypatch):
    """edge_tts 抛任意异常: 502, 不泄露原始 exc 字符串, 但带 retryable"""
    class FakeCommunicate:
        def __init__(self, text, voice):
            pass
        async def save(self, path):
            raise RuntimeError("internal: 192.168.1.1 refused connection /secret-token-xyz")

    _patch_communicate(monkeypatch, FakeCommunicate)
    r = _post_tts(client)

    assert r.status_code == 502
    assert r.json['success'] is False
    assert r.json['retryable'] is True
    assert r.json['retry_after'] >= 1
    # 关键: 原始异常字符串不该泄露给前端
    body = r.data.decode()
    assert '192.168.1.1' not in body
    assert 'secret-token' not in body
    assert 'RuntimeError' not in body


# === edge_tts 超时 ===

def test_tts_timeout_returns_504(client, monkeypatch):
    """asyncio.TimeoutError → 504, retryable=True, 提示稍后再试"""
    class SlowCommunicate:
        def __init__(self, text, voice):
            pass
        async def save(self, path):
            raise asyncio.TimeoutError()

    _patch_communicate(monkeypatch, SlowCommunicate)
    r = _post_tts(client)

    assert r.status_code == 504
    assert r.json['retryable'] is True
    assert r.json['retry_after'] == 5
    assert '超时' in r.json['error']


# === edge_tts 静默失败 (没抛也没文件) ===

def test_tts_silent_no_file_returns_502(client, monkeypatch):
    """save() 正常 return 但没写出文件 (edge-tts 偶发的 bug) → 502, retryable"""
    class QuietCommunicate:
        def __init__(self, text, voice):
            pass
        async def save(self, path):
            return  # 啥都不干, 假装成功

    _patch_communicate(monkeypatch, QuietCommunicate)
    r = _post_tts(client)

    assert r.status_code == 502
    assert r.json['retryable'] is True
    assert r.json['retry_after'] == 3
    assert '未返回' in r.json['error'] or '重试' in r.json['error']

