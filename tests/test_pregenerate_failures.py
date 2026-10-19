"""R10 新加的 pregenerate 失败可见性: _pregen_state 写 / tts_status 读。

之前 except Exception: pass 静默, 预生成全挂也察觉不到。
现在 /api/tts/status 返回 attempted/succeeded/failed/last_error, 可观测。
"""
import asyncio
import importlib

import pytest

from extensions import tts


@pytest.fixture
def pinned_edge_provider(monkeypatch):
    """把 TTS provider 钉成 edge(默认),不碰数据库。

    合成走哪个引擎是**运行时配置**决定的:家长在家长页把语音来源换成
    macos_say 之后,这些靠 monkeypatch `edge_tts.Communicate` 模拟失败的
    测试就会真的去调 `say`,于是"该失败"变成了"成功" —— 而且它还依赖
    这台机器上次被配成什么样,不是取决于被测代码。必须钉住。
    """
    from extensions import tts_providers
    monkeypatch.setattr(tts_providers, 'get_settings',
                        lambda: dict(tts_providers.DEFAULTS))

@pytest.fixture
def client(tmp_db, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


@pytest.fixture(autouse=True)
def reset_pregen_state():
    """每个 test 前 reset 状态 — 预生成是全局 dict, 跑过会变"""
    tts._pregen_state.update({'running': False, 'attempted': 0, 'succeeded': 0, 'failed': 0, 'last_error': None})
    yield


def test_pregen_state_initial_values():
    assert tts._pregen_state['running'] is False
    assert tts._pregen_state['attempted'] == 0
    assert tts._pregen_state['succeeded'] == 0
    assert tts._pregen_state['failed'] == 0
    assert tts._pregen_state['last_error'] is None


def test_synthesize_records_success(monkeypatch, tmp_path, pinned_edge_provider):
    """成功: attempted+1, succeeded+1, failed 不动, last_error 留 None"""
    monkeypatch.setattr('extensions.tts.TTS_DIR', tmp_path)

    class FakeComm:
        def __init__(self, text, voice, rate='+0%'): pass
        async def save(self, path):
            from pathlib import Path
            Path(path).write_bytes(b'fake-mp3')

    monkeypatch.setattr('extensions.tts.edge_tts.Communicate', FakeComm)

    ok = asyncio.run(tts._pregen_synthesize('hello world'))
    assert ok is True
    assert tts._pregen_state['attempted'] == 1
    assert tts._pregen_state['succeeded'] == 1
    assert tts._pregen_state['failed'] == 0
    assert tts._pregen_state['last_error'] is None


def test_synthesize_records_failure(monkeypatch, tmp_path, pinned_edge_provider):
    """失败: attempted+1, succeeded 不动, failed+1, last_error 写好"""
    monkeypatch.setattr('extensions.tts.TTS_DIR', tmp_path)

    class FakeComm:
        def __init__(self, text, voice, rate='+0%'): pass
        async def save(self, path):
            raise ConnectionError("network down")

    monkeypatch.setattr('extensions.tts.edge_tts.Communicate', FakeComm)

    ok = asyncio.run(tts._pregen_synthesize('hello'))
    assert ok is False
    assert tts._pregen_state['attempted'] == 1
    assert tts._pregen_state['succeeded'] == 0
    assert tts._pregen_state['failed'] == 1
    assert 'ConnectionError' in tts._pregen_state['last_error']
    assert 'network down' in tts._pregen_state['last_error']


def test_synthesize_existing_file_is_noop_skip(monkeypatch, tmp_path, pinned_edge_provider):
    """文件已存在: 走 attempted+1, succeeded+1, 不调 edge_tts。"""
    monkeypatch.setattr('extensions.tts.TTS_DIR', tmp_path)
    # 预先放一个 audio file
    h = tts._cache_key('cached-text', tts.DEFAULT_VOICE)
    (tmp_path / f'{h}.mp3').write_bytes(b'preexisting')

    called = []
    class FakeComm:
        def __init__(self, text, voice, rate='+0%'): called.append(text)
        async def save(self, path): pass
    monkeypatch.setattr('extensions.tts.edge_tts.Communicate', FakeComm)

    ok = asyncio.run(tts._pregen_synthesize('cached-text'))
    assert ok is True
    assert called == [], f'edge_tts 不该被调用, 实际调了 {called}'
    assert tts._pregen_state['attempted'] == 1
    assert tts._pregen_state['succeeded'] == 1


def test_tts_status_exposes_pregen_state(client):
    """/api/tts/status 返回 pregenerate 字段, 含 attempted/succeeded/failed/last_error"""
    r = client.get('/api/tts/status')
    assert r.status_code == 200
    pg = r.json['pregenerate']
    for k in ('running', 'attempted', 'succeeded', 'failed', 'last_error'):
        assert k in pg, f'pregenerate 字段缺 {k}'
