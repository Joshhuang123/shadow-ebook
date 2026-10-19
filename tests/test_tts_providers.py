"""TTS provider 可切换性的守护。

为什么这些测试必须存在
----------------------
「接自己的 TTS」是一个很容易被改坏、又很难被察觉的功能:家长配好之后,
朗读**看起来**是正常的(前端会自动降级到设备语音),只有仔细听才发现
「咦,用的还是旧的声音」。所以这里把几条不变量钉死:

1. 缓存 key 必须跟着 provider 走 —— 否则换了引擎还在读旧音频,
   表现就是「设置改了没用」。
2. api_key 永远不出现在任何接口返回里 —— 它必须留在服务端。
3. 写设置 / 试听必须鉴权 —— 这是家长配置,孩子端不该能改。
4. device 模式下服务端拒绝合成,而不是默默合成。
"""
import json

import pytest


@pytest.fixture
def client(tmp_db):
    import importlib
    from extensions import db
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


@pytest.fixture(autouse=True)
def _clean_tts_section(tmp_db):
    """每个用例从「没配过」开始,避免互相污染。

    依赖 tmp_db:不依赖的话,这个清理会写到**生产库**,把家长在页面上
    配好的语音来源抹掉。测试不能有这种副作用。
    """
    from extensions import tts_providers
    tts_providers.clear_settings()
    yield
    tts_providers.clear_settings()


@pytest.fixture
def pinned_edge_provider(monkeypatch):
    """把 provider 钉成 edge(默认值),不碰数据库。

    有些老测试靠 monkeypatch `edge_tts.Communicate` 来模拟合成失败。
    但合成走哪个引擎是**运行时配置**决定的 —— 家长在页面上换成
    macos_say,这些测试就会真的去调 `say`,然后"失败用例"莫名其妙地成功了。
    钉住 provider,测试的结果就只取决于被测代码。
    """
    from extensions import tts_providers
    monkeypatch.setattr(tts_providers, 'get_settings',
                        lambda: dict(tts_providers.DEFAULTS))


def _login(client):
    """家长登录。默认 PIN 是 0000,见 extensions/auth.py。"""
    r = client.post('/api/parent/login', json={'pin': '0000'})
    assert r.get_json().get('success'), r.get_data(as_text=True)[:200]


# ---------- 设置读写 ----------
def test_defaults_when_unconfigured(client):
    r = client.get('/api/tts/settings')
    j = r.get_json()
    assert j['success'] is True
    assert j['provider'] == 'edge'
    assert j['server_synthesis'] is True


def test_settings_roundtrip(client):
    _login(client)
    r = client.post('/api/tts/settings', json={
        'provider': 'openai_compatible',
        'base_url': 'http://192.168.1.50:8000/v1',
        'model': 'tts-1',
        'voice': 'alloy',
        'api_key': 'sk-secret-value',
    })
    assert r.get_json()['success'] is True

    j = client.get('/api/tts/settings').get_json()
    s = j['settings']
    assert s['provider'] == 'openai_compatible'
    assert s['base_url'] == 'http://192.168.1.50:8000/v1'
    assert s['voice'] == 'alloy'
    assert s['has_api_key'] is True


def test_api_key_never_leaves_the_server(client):
    """密钥只在服务端。公开字段和家长字段里都不能出现本体。"""
    _login(client)
    client.post('/api/tts/settings', json={
        'provider': 'openai_compatible',
        'base_url': 'http://10.0.0.5:8000/v1',
        'api_key': 'sk-do-not-leak-me',
    })
    raw = client.get('/api/tts/settings').get_data(as_text=True)
    assert 'sk-do-not-leak-me' not in raw
    assert client.get('/api/tts/settings').get_json()['settings']['has_api_key'] is True


def test_unauthenticated_cannot_write_settings(client):
    r = client.post('/api/tts/settings', json={'provider': 'device'})
    assert r.status_code == 401


def test_unauthenticated_cannot_test(client):
    r = client.post('/api/tts/test', json={})
    assert r.status_code == 401


def test_reject_unknown_provider(client):
    _login(client)
    r = client.post('/api/tts/settings', json={'provider': 'skynet'})
    assert r.status_code == 400
    # 失败不应该把已有的设置改坏
    assert client.get('/api/tts/settings').get_json()['provider'] == 'edge'


def test_null_means_unchanged(client):
    """前端对「密钥输入框留空」传 null,含义是"不要动它",不是"清空"。"""
    _login(client)
    client.post('/api/tts/settings', json={
        'provider': 'openai_compatible', 'base_url': 'http://a:1/v1', 'api_key': 'keep-me'})
    client.post('/api/tts/settings', json={'voice': 'nova'})  # 不带 api_key
    s = client.get('/api/tts/settings').get_json()['settings']
    assert s['has_api_key'] is True, '只改音色的保存动作把密钥冲掉了'
    assert s['voice'] == 'nova'


def test_clear_key_endpoint(client):
    _login(client)
    client.post('/api/tts/settings', json={
        'provider': 'openai_compatible', 'base_url': 'http://a:1/v1', 'api_key': 'bye'})
    client.post('/api/tts/settings/clear-key')
    s = client.get('/api/tts/settings').get_json()['settings']
    assert s['has_api_key'] is False
    # 只清密钥,端点不能跟着没
    assert s['base_url'] == 'http://a:1/v1'


def test_reset_restores_defaults(client):
    _login(client)
    client.post('/api/tts/settings', json={'provider': 'device', 'voice': 'x'})
    client.delete('/api/tts/settings')
    j = client.get('/api/tts/settings').get_json()
    assert j['provider'] == 'edge'


# ---------- 缓存隔离 ----------
def test_cache_fingerprint_changes_with_provider(client):
    from extensions import tts_providers
    before = tts_providers.cache_fingerprint()
    tts_providers.save_settings({'provider': 'openai_compatible',
                                  'base_url': 'http://x:1/v1', 'voice': 'v1'})
    mid = tts_providers.cache_fingerprint()
    tts_providers.save_settings({'voice': 'v2'})
    after = tts_providers.cache_fingerprint()
    assert len({before, mid, after}) == 3, \
        '换了引擎/音色但缓存指纹没变 —— 旧音频会继续被命中,听起来像"设置没生效"'


def test_cache_fingerprint_ignores_api_key(client):
    """换密钥不该让全部缓存作废 —— 那会让家长以为要重下几千个音频。"""
    from extensions import tts_providers
    tts_providers.save_settings({'provider': 'openai_compatible',
                                  'base_url': 'http://x:1/v1', 'api_key': 'k1'})
    a = tts_providers.cache_fingerprint()
    tts_providers.save_settings({'api_key': 'k2'})
    assert tts_providers.cache_fingerprint() == a


def test_cache_key_includes_fingerprint(client):
    """端到端:同名同音色,两个 provider 必须算出不同的缓存文件名。"""
    import hashlib
    from extensions import tts_providers

    def key(provider, extra=None):
        tts_providers.save_settings({'provider': provider, **(extra or {})})
        fp = tts_providers.cache_fingerprint()
        voice = tts_providers.voice_for(tts_providers.get_settings())
        return hashlib.md5(f'{fp}|{voice}|hello'.encode()).hexdigest()[:12]

    a = key('edge')
    b = key('openai_compatible', {'base_url': 'http://x:1/v1'})
    assert a != b


def test_audio_ext_follows_format(client):
    from extensions import tts_providers
    tts_providers.save_settings({'provider': 'openai_compatible',
                                  'base_url': 'http://x:1/v1', 'response_format': 'wav'})
    assert tts_providers.audio_ext(tts_providers.get_settings()) == 'wav'


# ---------- device 模式 ----------
def test_device_mode_refuses_server_synthesis(client):
    _login(client)
    client.post('/api/tts/settings', json={'provider': 'device'})
    j = client.get('/api/tts/settings').get_json()
    assert j['server_synthesis'] is False

    r = client.post('/api/tts', json={'text': 'hello'})
    assert r.status_code == 409
    body = r.get_json()
    assert body['success'] is False
    # 409 是个约定:前端看到 use_device_voice 就知道该走 speechSynthesis
    assert body['use_device_voice'] is True


def test_device_mode_skips_pregeneration(client):
    from extensions import tts
    from extensions import tts_providers
    tts_providers.save_settings({'provider': 'device'})
    tts._pregen_state.update({'attempted': 0, 'succeeded': 0, 'failed': 0})
    tts.pregenerate_all_tts()
    assert tts._pregen_state['attempted'] == 0, 'device 模式下还在白跑服务端合成'
    assert tts._pregen_state['skipped'] == 'device'


def test_status_reports_provider(client):
    j = client.get('/api/tts/status').get_json()
    assert j['provider'] == 'edge'
    assert j['server_synthesis'] is True


# ---------- 合成适配器(不打真网络) ----------
def test_openai_compat_missing_base_url_is_actionable(client):
    from extensions import tts_providers
    r = tts_providers.check_connection({
        'provider': 'openai_compatible', 'base_url': '', 'voice': 'a',
        'model': '', 'api_key': '', 'response_format': 'mp3', 'speed': 1.0, 'timeout': 5,
    })
    assert r['success'] is False
    # 家长要看到能照着改的话,不是 "URLError"
    assert '地址' in r['error']


def test_openai_compat_unreachable_host_is_actionable(monkeypatch):
    """连不上要说的是"连不上",不是把 socket 异常抛给家长。"""
    import urllib.error
    from extensions import tts_providers

    def boom(*a, **kw):
        raise urllib.error.URLError('Connection refused')

    monkeypatch.setattr('urllib.request.urlopen', boom)
    r = tts_providers.check_connection({
        'provider': 'openai_compatible', 'base_url': 'http://127.0.0.1:9/v1',
        'voice': 'a', 'model': '', 'api_key': '', 'response_format': 'mp3',
        'speed': 1.0, 'timeout': 5,
    })
    assert r['success'] is False
    assert '连不上' in r['error']


def test_openai_compat_http_error_is_mapped(monkeypatch):
    """401/404 要翻译成家长看得懂的话。"""
    import io
    import urllib.error
    from extensions import tts_providers

    def boom(*a, **kw):
        raise urllib.error.HTTPError(
            'http://x', 401, 'Unauthorized', {}, io.BytesIO(b'bad key'))

    monkeypatch.setattr('urllib.request.urlopen', boom)
    r = tts_providers.check_connection({
        'provider': 'openai_compatible', 'base_url': 'http://127.0.0.1:9/v1',
        'voice': 'a', 'model': '', 'api_key': 'k', 'response_format': 'mp3',
        'speed': 1.0, 'timeout': 5,
    })
    assert r['success'] is False
    assert '密钥' in r['error']


def test_openai_compat_json_error_body_is_caught(monkeypatch):
    """有些服务出错时返回 JSON 而不是音频。不拦一道的话,
    前端会拿着 {"error": ...} 去 new Audio(),只得到一个静默失败。"""
    import io
    from extensions import tts_providers

    class FakeResp:
        def __init__(self, data):
            self._d = data

        def read(self):
            return self._d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr('urllib.request.urlopen',
                        lambda *a, **kw: FakeResp(b'{"error": "no such voice"}'))
    r = tts_providers.check_connection({
        'provider': 'openai_compatible', 'base_url': 'http://127.0.0.1:9/v1',
        'voice': 'a', 'model': '', 'api_key': '', 'response_format': 'mp3',
        'speed': 1.0, 'timeout': 5,
    })
    assert r['success'] is False
    assert '音频' in r['error']


def test_speed_is_clamped(client):
    from extensions import tts_providers
    tts_providers.save_settings({'speed': 99})
    assert tts_providers.get_settings()['speed'] == 2.0
    tts_providers.save_settings({'speed': 0.01})
    assert tts_providers.get_settings()['speed'] == 0.5
