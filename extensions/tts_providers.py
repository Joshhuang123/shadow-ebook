"""
Owns: TTS provider abstraction (edge / openai-compatible / device) + parent-configurable settings.

Does NOT own: audio caching + LRU eviction + file serving (/api/tts, audio/) — that's tts.py.

为什么要有这一层
----------------
edge-tts 是「免费但要联网」的上游。自用工具一旦断网、对方限流,或者孩子想用
妈妈电脑上的本地语音模型,整条朗读链路就哑了。家长应该能在页面上换一个,
而不是去改环境变量重启服务。

三种 provider
-------------
edge              微软 Edge TTS(默认)。免费、音色多,要联网。
openai_compatible 任何实现 POST {base_url}/audio/speech 的服务。OpenAI 官方、
                  Azure 转发、以及大量本地推理服务(Piper / GPT-SoVITS 等)的
                  OpenAI 兼容外壳都吃这一套。api_key 可以留空 —— 本地服务通常不需要鉴权。
device            服务端完全不合成。平板/电脑用自己的 speechSynthesis 念,
                  真正零依赖、零延迟、完全离线。

设置存在 parent_section['tts'],只有家长(PIN)能写。读接口只吐不含密钥的部分。
"""
import hashlib
import json
import logging
import os
import sys
import tempfile
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


PROVIDERS = ('edge', 'openai_compatible', 'macos_say', 'device')

# provider 的默认设置。改这里的值等于给「恢复默认」一个基准。
DEFAULTS = {
    'provider': 'edge',
    'base_url': '',
    'api_key': '',
    'model': '',
    'voice': '',
    'response_format': 'mp3',
    'speed': 1.0,
    'timeout': 20,
    # macos_say 专用:语速(词/分钟)和系统音色名
    'say_voice': 'Samantha',
    'say_rate': 160,
}

# OpenAI /audio/speech 官方支持的返回格式。别的值本地服务可能也认,
# 但不认识的会直接 400,所以这里只放通用的这几个。
KNOWN_FORMATS = ('mp3', 'opus', 'aac', 'flac', 'wav', 'pcm')

EXT_FOR_FORMAT = {
    'mp3': 'mp3', 'opus': 'ogg', 'aac': 'aac',
    'flac': 'flac', 'wav': 'wav', 'pcm': 'pcm',
}

SECTION = 'tts'

# 试听音频内联返回的上限。一句英文大概 30-60KB,留 2MB 余量,
# 防止家长把试听文本填成长文时把响应撑爆。
_MAX_INLINE_AUDIO_BYTES = 2 * 1024 * 1024


# === 设置读写 ===
def _load_raw() -> dict:
    """读 parent_section['tts'],坏数据当没配。延迟 import 避免循环依赖。"""
    try:
        from extensions import parent_data
        return parent_data._load_section(SECTION) or {}
    except Exception as e:  # DB 还没初始化 / 表不存在
        logger.debug('TTS 设置读取失败,按默认处理: %s', e)
        return {}


def get_settings() -> dict:
    """合并后的完整设置(DEFAULTS 打底)。调用方拿到的永远是完整 dict。"""
    raw = _load_raw()
    merged = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in raw and raw[k] not in (None, ''):
            merged[k] = raw[k]
    if merged['provider'] not in PROVIDERS:
        merged['provider'] = DEFAULTS['provider']
    if merged['response_format'] not in KNOWN_FORMATS:
        merged['response_format'] = DEFAULTS['response_format']
    try:
        merged['speed'] = float(merged['speed'])
    except (TypeError, ValueError):
        merged['speed'] = DEFAULTS['speed']
    merged['speed'] = max(0.5, min(2.0, merged['speed']))
    try:
        merged['timeout'] = int(merged['timeout'])
    except (TypeError, ValueError):
        merged['timeout'] = DEFAULTS['timeout']
    merged['timeout'] = max(5, min(120, merged['timeout']))
    try:
        merged['say_rate'] = int(merged['say_rate'])
    except (TypeError, ValueError):
        merged['say_rate'] = DEFAULTS['say_rate']
    # 孩子听:100 太快,300 太慢。macOS say 自己的范围是 150~300,
    # 但下限放宽一点,让「很慢地念」这个选项对刚开始学的孩子可用。
    merged['say_rate'] = max(100, min(300, merged['say_rate']))
    merged['say_voice'] = str(merged['say_voice'] or DEFAULTS['say_voice'])
    return merged


def save_settings(patch: dict) -> dict:
    """合并保存。只接受 DEFAULTS 里的 key,其余静默丢弃。

    整段覆盖而不是逐 key 合并:家长在表单里清空「API Key」应该真的清空,
    增量合并做不到区分「没填」和「要清空」。
    """
    # 在**当前设置**上打补丁,不是在默认值上重建。
    # 早先写成 `merged = DEFAULTS + patch`,后果是:家长只想改个音色,
    # 没传的 api_key 就被重置回空 —— 密钥无声地丢了,得重新输一遍。
    #
    # 两种「空」要分清:
    #   None  = 这次不改这个字段(前端对"密钥输入框留空"的表达)
    #   ''    = 清空(base_url / voice 这类字段用它来清)
    # 清空密钥走单独的 /api/tts/settings/clear-key,避免歧义。
    merged = get_settings()
    for k in DEFAULTS:
        if k in patch and patch[k] is not None:
            merged[k] = patch[k]
    if merged['provider'] not in PROVIDERS:
        raise ValueError(f"未知的 provider: {merged['provider']!r},支持 {PROVIDERS}")
    if merged['response_format'] not in KNOWN_FORMATS:
        raise ValueError(f"未知的音频格式: {merged['response_format']!r},支持 {KNOWN_FORMATS}")
    try:
        from extensions import parent_data
        parent_data._save_section(SECTION, merged)
    except Exception as e:
        logger.error('TTS 设置保存失败: %s', e)
        raise
    return get_settings()


def clear_api_key() -> dict:
    """只清密钥,其他设置不动。

    为什么单独开一个接口:密钥输入框留空必须表示"不修改" —— 否则家长
    每次改模型名都得重新输一遍长密钥,体验极差。但"清空"又确实需要,
    两者只能靠不同动作表达。
    """
    s = get_settings()
    s['api_key'] = ''
    try:
        from extensions import parent_data
        parent_data._save_section(SECTION, s)
    except Exception as e:
        logger.error('TTS 密钥清除失败: %s', e)
        raise
    return get_settings()


def clear_settings() -> dict:
    """恢复默认。"""
    try:
        from extensions import parent_data
        parent_data._save_section(SECTION, dict(DEFAULTS))
    except Exception:
        pass
    return get_settings()


# === 对外暴露给前端的部分(绝不含密钥) ===
def public_settings() -> dict:
    """给孩子端页面看的设置。

    api_key 只回 has_api_key 布尔值。密钥必须留在这个进程里 ——
    前端拿到它就等于广播到局域网里每一个设备上。
    """
    s = get_settings()
    return {
        'provider': s['provider'],
        # 孩子端只需要知道音色名;base_url/model 对播放没有意义,不外传。
        'voice': s['voice'],
        # provider=device 时前端应该完全绕开 /api/tts,直接用设备自带语音。
        'server_synthesis': s['provider'] != 'device',
    }


def parent_settings_view() -> dict:
    """家长端看的设置:比 public 多端点/模型/格式,仍然不含密钥本体。"""
    s = get_settings()
    return {
        'provider': s['provider'],
        'base_url': s['base_url'],
        'model': s['model'],
        'voice': s['voice'],
        'say_voice': s['say_voice'],
        'say_rate': s['say_rate'],
        'response_format': s['response_format'],
        'speed': s['speed'],
        'timeout': s['timeout'],
        'has_api_key': bool(s['api_key']),
        'providers': list(PROVIDERS),
        'formats': list(KNOWN_FORMATS),
    }


# === 缓存指纹 ===
def cache_fingerprint() -> str:
    """provider 指纹,参与音频缓存文件名。

    必须包含 provider/base_url/model/voice —— 否则家长把引擎从 edge 换成
    本地模型,旧的 mp3 还在缓存里,读出来的还是上一个引擎的声音,而且
    永远清不掉(看着像"设置没生效")。

    刻意**不含 api_key**:家长换 key 不该让全部缓存作废。
    """
    s = get_settings()
    raw = '|'.join(str(s[k]) for k in ('provider', 'base_url', 'model', 'voice',
                                       'response_format', 'speed'))
    return hashlib.md5(raw.encode()).hexdigest()[:8]


def voice_for(settings: dict) -> str:
    """实际下发给引擎的音色:家长配了就用配的,没配就用默认值。"""
    v = (settings.get('voice') or '').strip()
    if v:
        return v
    if settings.get('provider') == 'edge':
        return os.environ.get('DEFAULT_TTS_VOICE', 'en-US-AriaNeural')
    if settings.get('provider') == 'macos_say':
        return settings.get('say_voice') or DEFAULTS['say_voice']
    return 'alloy'


def audio_ext(settings: dict) -> str:
    """缓存文件扩展名。边车存成 .mp3 但内容是 opus 的话,部分播放器会拒绝。"""
    if settings.get('provider') == 'edge':
        return 'mp3'
    return EXT_FOR_FORMAT.get(settings.get('response_format'), 'mp3')


# === 合成 ===
class TTSError(RuntimeError):
    """合成失败。message 面向家长,detail 面向日志。

    http_status 保留区分:超时是 504,其他是 502。
    这不是洁癖 —— 前端对这两者的退避策略不同(retry_after 5s vs 3s),
    而且 504 在语义上就是"上游没及时回",压成 502 会让排查变难。
    """

    def __init__(self, message: str, detail: str = '', http_status: int = 502,
                 retry_after: int = 3):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.http_status = http_status
        self.retry_after = retry_after


def synthesize(text: str, voice: str = '', settings: dict = None) -> tuple[bytes, str]:
    """按配置的 provider 合成。返回 (音频字节, 文件扩展名)。

    provider=device 时抛 TTSError —— 调用方(tts.py / 前端)应该改成走设备自带语音。
    """
    s = settings or get_settings()
    provider = s.get('provider', 'edge')
    used_voice = voice or voice_for(s)

    if provider == 'edge':
        return _synthesize_edge(text, used_voice, s.get('timeout', 20)), 'mp3'
    if provider == 'openai_compatible':
        return _synthesize_openai_compat(text, used_voice, s), audio_ext(s)
    if provider == 'macos_say':
        return _synthesize_macos_say(text, used_voice, s), 'mp3'
    if provider == 'device':
        raise TTSError('当前设置为「用平板自带语音」,服务端不合成')
    raise TTSError(f'未知的 TTS provider: {provider!r}')


def _synthesize_edge(text: str, voice: str, timeout: float = 20) -> bytes:
    """edge-tts 直接吐 mp3 字节。

    edge_tts.Communicate.save() 只能写文件,所以借一个临时文件中转。
    """
    import asyncio
    import edge_tts

    async def _run():
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tf:
            path = tf.name
        try:
            await edge_tts.Communicate(text, voice=voice).save(path)
            with open(path, 'rb') as f:
                return f.read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    try:
        data = asyncio.run(asyncio.wait_for(_run(), timeout=timeout))
    except asyncio.TimeoutError as e:
        raise TTSError('合成超时,上游没响应', f'edge-tts timeout voice={voice}',
                       http_status=504, retry_after=5) from e
    except Exception as e:
        raise TTSError('合成失败', f'{type(e).__name__}: {e}') from e
    if not data:
        # 不抛异常也没写出文件 —— 服务端静默失败,单独报,
        # 和「连不上」区分开,家长看到的提示才有指向性。
        raise TTSError('语音服务未返回音频, 请稍后再试', 'empty response')
    return data


def _synthesize_macos_say(text: str, voice: str, s: dict) -> bytes:
    """用 macOS 自带的 `say` 合成 —— 免费、离线、随服务器走。

    为什么需要它:
    - 平板浏览器的 speechSynthesis 音色**很不可控**:iPad 上可能只挑到一个
      低质量音色,换台设备音色就变了,而且家长没法调。
    - `say` 在服务器上,音色固定,还能调语速 —— 对刚开始学英语的孩子,
      慢一点比"标准语速"更有用。

    音质定位要诚实:系统音色是"够用",不是 neural 级别的自然。
    想要真正自然的音质,去配一个 openai_compatible(见 docs/TTS.md)。
    """
    import shutil
    import subprocess
    import tempfile

    if sys.platform != 'darwin' or not shutil.which('say'):
        raise TTSError('这个服务不在 macOS 上,没有系统语音',
                       f'platform={sys.platform} say={shutil.which("say")}')

    try:
        rate = int(s.get('say_rate') or DEFAULTS['say_rate'])
    except (TypeError, ValueError):
        rate = DEFAULTS['say_rate']
    rate = max(100, min(300, rate))

    with tempfile.TemporaryDirectory() as tmpdir:
        aiff = os.path.join(tmpdir, 'out.aiff')
        try:
            proc = subprocess.run(
                ['say', '-v', voice, '-r', str(rate), '-o', aiff, '--', text],
                capture_output=True, timeout=s.get('timeout', 20))
        except subprocess.TimeoutExpired as e:
            raise TTSError('合成超时', f'say timeout voice={voice}') from e
        if proc.returncode != 0:
            err = (proc.stderr or b'').decode(errors='replace')[:200]
            raise TTSError(f'系统语音 {voice} 不可用', err)
        if not os.path.exists(aiff) or os.path.getsize(aiff) == 0:
            raise TTSError('系统语音没有生成音频', 'say produced no output')

        # 转成 mp3:浏览器/Safari 通吃,体积也只有 aiff 的 1/5。
        # ffmpeg 不在就退回 m4a(aac),Safari 直接能播,其它浏览器也能。
        if shutil.which('ffmpeg'):
            mp3 = os.path.join(tmpdir, 'out.mp3')
            try:
                subprocess.run(
                    ['ffmpeg', '-y', '-loglevel', 'error', '-i', aiff,
                     '-codec:a', 'libmp3lame', '-q:a', '4', mp3],
                    capture_output=True, timeout=s.get('timeout', 20))
            except subprocess.TimeoutExpired:
                pass
            if os.path.exists(mp3) and os.path.getsize(mp3) > 0:
                with open(mp3, 'rb') as f:
                    return f.read()

        m4a = os.path.join(tmpdir, 'out.m4a')
        try:
            subprocess.run(
                ['afconvert', '-f', 'm4af', '-d', 'aac', '-b', '64000', aiff, m4a],
                capture_output=True, timeout=s.get('timeout', 20))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        if os.path.exists(m4a) and os.path.getsize(m4a) > 0:
            with open(m4a, 'rb') as f:
                return f.read()

        with open(aiff, 'rb') as f:
            return f.read()


def _synthesize_openai_compat(text: str, voice: str, s: dict) -> bytes:
    """POST {base_url}/audio/speech,拿音频字节。

    这一类接口的形状高度一致(OpenAI 定的),本地推理服务基本都照抄,
    所以不需要为 Piper / GPT-SoVITS 各写一个适配器。
    """
    base = (s.get('base_url') or '').strip().rstrip('/')
    if not base:
        raise TTSError('还没填服务地址', 'base_url 为空')

    url = base if base.endswith('/audio/speech') else f'{base}/audio/speech'
    payload = {
        'model': s.get('model') or 'tts-1',
        'input': text,
        'voice': voice,
        'response_format': s.get('response_format') or 'mp3',
    }
    speed = s.get('speed')
    if speed and abs(float(speed) - 1.0) > 0.01:
        payload['speed'] = float(speed)

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            'Content-Type': 'application/json',
            'Accept': 'audio/mpeg',
        },
        method='POST',
    )
    key = (s.get('api_key') or '').strip()
    if key:
        req.add_header('Authorization', f'Bearer {key}')

    try:
        with urllib.request.urlopen(req, timeout=s.get('timeout', 20)) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')[:300]
        hint = {
            401: '服务拒绝了密钥,检查 API Key',
            403: '服务拒绝了密钥,检查 API Key',
            404: '这个地址没有 /audio/speech 接口,检查服务地址',
        }.get(e.code, f'服务返回 HTTP {e.code}')
        raise TTSError(hint, f'HTTP {e.code}: {body}') from e
    except urllib.error.URLError as e:
        # 自家服务最常见的失败:地址写错 / 服务没起 / 端口不通
        raise TTSError('连不上这个服务,检查地址和端口', f'URLError: {e.reason}') from e
    except Exception as e:
        raise TTSError('请求失败', f'{type(e).__name__}: {e}') from e

    if not data:
        raise TTSError('服务返回了空内容', 'empty body')
    # 有些服务出错时返回 JSON 而不是音频,提前拦一道,免得前端拿着
    # 一段 {"error": ...} 去 new Audio() 只听到一个静默失败。
    if data[:1] == b'{':
        raise TTSError('服务返回的是错误信息,不是音频',
                       data.decode(errors='replace')[:300])
    return data


def check_connection(settings: dict = None, with_audio: bool = False) -> dict:
    """试听用:合成一句短文本,返回耗时和字节数。

    失败时**不抛异常**,把原因放进 error —— 试听按钮要显示具体原因,
    不是抛一个栈给家长看。
    """
    import time
    s = settings or get_settings()
    started = time.monotonic()
    try:
        data, ext = synthesize('Hello! This is a test.', settings=s)
    except TTSError as e:
        return {'success': False, 'error': e.message, 'detail': e.detail,
                'ms': int((time.monotonic() - started) * 1000)}
    except Exception as e:
        return {'success': False, 'error': '未知错误', 'detail': f'{type(e).__name__}: {e}',
                'ms': int((time.monotonic() - started) * 1000)}
    out = {
        'success': True,
        'ms': int((time.monotonic() - started) * 1000),
        'bytes': len(data),
        'ext': ext,
    }
    if with_audio:
        # 试听要真的听见声音。只回「耗时 320ms」家长没法判断音色对不对。
        # 走 base64 内联返回,而不是写进缓存 —— 试听文本每次都一样的话
        # 会把缓存 key 占住,而家长真正想试听的是**表单里还没保存的草稿**。
        import base64
        if len(data) <= _MAX_INLINE_AUDIO_BYTES:
            out['audio_b64'] = base64.b64encode(data).decode('ascii')
    return out
