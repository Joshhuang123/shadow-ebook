"""
Owns: TTS endpoint, TTS cache eviction policy (LRU via atime), TTS pregeneration background task,
audio file serving, /api/tts/status endpoint.
Does NOT own: course content (courses.py), book content (books.py), auth/rate-limit helpers (auth.py).
"""
import asyncio
import hashlib
import json
import logging
import os
import threading
import uuid
from pathlib import Path

# edge_tts 真正的使用点在 tts_providers(按需 import),这里只保留一个引用,
# 原因有两个:
#   1) 测试会 monkeypatch `extensions.tts.edge_tts.Communicate`。两边拿到的是
#      **同一个模块对象**,所以老测试的打桩照样生效,不用改。
#   2) 保持 edge-tts 可选:将来想跑纯本地部署(不装微软那套依赖)时,
#      这个文件仍然能 import 成功。
try:
    import edge_tts  # noqa: F401
except ImportError:  # pragma: no cover - 只在没装 edge-tts 的机器上触发
    edge_tts = None
from flask import jsonify, request, send_from_directory, session

from extensions.auth import _api_rate_limit_ok, require_parent_auth
from extensions import tts_providers


logger = logging.getLogger(__name__)


TTS_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
TTS_CACHE_MAX_FILES = 100_000
AUDIO_ROOT = Path(__file__).resolve().parent.parent / 'audio'
TTS_DIR = AUDIO_ROOT / 'tts'
DEFAULT_VOICE = 'en-US-AriaNeural'
TTS_TIMEOUT_SEC = 15  # edge-tts 卡死时 worker 也不能无限等


# === TTS 缓存淘汰 (真正的 LRU: 基于 atime, mtime 不可靠) ===
# provider 支持的音频容器。opus 存成 .ogg(浏览器认这个扩展名)。
_AUDIO_SUFFIXES = ('.mp3', '.ogg', '.aac', '.flac', '.wav', '.pcm')


def _audio_files() -> list:
    """列出缓存里的音频文件。

    只认真音频文件:不能无脑 `glob('*')` —— 目录、写入中的 .tmp、
    以及任何被丢进这个目录的别的东西都会被数进去,状态页的计数就骗人了。
    """
    if not TTS_DIR.exists():
        return []
    out = []
    for f in TTS_DIR.iterdir():
        try:
            if (f.is_file() and not f.name.startswith('.')
                    and f.suffix.lower() in _AUDIO_SUFFIXES):
                out.append(f)
        except OSError:
            continue
    return out


def _cache_key(text: str, voice: str = '', settings: dict = None) -> str:
    """缓存文件名(不含扩展名)。

    刻意把 provider 指纹算进去:家长把引擎从微软换成自建服务之后,
    旧音频是**孤儿** —— 永远不会被命中,但还占着磁盘,而且听起来
    "设置没生效"。key 里带着引擎,新旧音频就天然分开了。

    提取成函数而不是在两处各写一遍:重复的 md5 公式迟早会被改歪。
    """
    settings = settings if settings is not None else tts_providers.get_settings()
    # 指纹跟随「当前已保存的设置」,而不是这次传进来的 settings:
    # 缓存文件必须在保存设置之前就已存在,不然第一次合成就会算到另一个 key。
    fp = tts_providers.cache_fingerprint()
    used_voice = voice or tts_providers.voice_for(settings)
    return hashlib.md5(f'{fp}|{used_voice}|{text}'.encode()).hexdigest()[:12]


def _evict_tts_cache(audio_dir: Path):
    """超过 TTS_CACHE_MAX_BYTES / TTS_CACHE_MAX_FILES 时,按 atime 删最旧访问的文件。

    Phase 2 修: 之前用 mtime (生成时间),改用 atime (最后访问时间)。
    atime 在 text_to_speech 缓存命中 + serve_audio 命中时由 os.utime 更新。
    """
    if not audio_dir.exists():
        return
    try:
        entries = []
        for f in audio_dir.glob('*.mp3'):
            try:
                st = f.stat()
            except OSError:
                continue
            entries.append((f, st.st_atime, st.st_size))

        # 0 字节文件优先删 (上回生成失败的残留)
        evicted_count = 0
        for f, _, sz in [e for e in entries if e[2] == 0]:
            try:
                f.unlink()
                evicted_count += 1
            except OSError:
                pass
        entries = [e for e in entries if e[2] > 0]

        total_bytes = sum(e[2] for e in entries)
        if total_bytes <= TTS_CACHE_MAX_BYTES and len(entries) <= TTS_CACHE_MAX_FILES:
            return

        # 按 atime 升序排 (最旧访问在前)
        entries.sort(key=lambda e: e[1])

        # 关键: 迭代 entries 副本, remaining_count 跟着删, 避免边迭代边 mutate 跳项
        remaining_count = len(entries)
        for f, _, sz in list(entries):
            if total_bytes <= TTS_CACHE_MAX_BYTES and remaining_count <= TTS_CACHE_MAX_FILES:
                break
            try:
                f.unlink()
                total_bytes -= sz
                remaining_count -= 1
                evicted_count += 1
            except OSError:
                pass

        if evicted_count:
            logger.info(f"TTS 缓存淘汰: 删除 {evicted_count} 个最旧访问文件, 剩余 {len(entries)} 个 / {total_bytes // (1024*1024)}MB")
    except Exception as e:
        logger.warning(f"TTS cache evict error: {e}")


def _touch_atime(audio_path: Path):
    """更新 atime 到当前,失败也不抛 (用于 LRU 跟踪)"""
    try:
        os.utime(audio_path, None)  # None = atime 和 mtime 都设为 now
    except OSError as e:
        logger.warning(f"touch atime 失败 {audio_path}: {e}")


# === 启动时预生成 TTS 音频 ===
# 预生成过程统计: pregenerate_all_tts 写, /api/tts/status 读
_pregen_state = {'running': False, 'attempted': 0, 'succeeded': 0, 'failed': 0, 'last_error': None}

# 预生成并发数。串行合成一本 800 句的书要 10+ 分钟,孩子早开读了;
# 开太高又容易把 edge-tts 上游打到限流。4 是稳的,SHADOW_TTS_PREGEN_CONCURRENCY 可调。
_PREGEN_CONCURRENCY_DEFAULT = 4
_PREGEN_CONCURRENCY_MAX = 16


def _pregen_concurrency() -> int:
    raw = os.environ.get('SHADOW_TTS_PREGEN_CONCURRENCY', '')
    try:
        v = int(raw)
    except ValueError:
        return _PREGEN_CONCURRENCY_DEFAULT
    return max(1, min(v, _PREGEN_CONCURRENCY_MAX))


def _collect_pregen_texts() -> list:
    """从 SQLite 收集需要预生成的书内句子,全局去重后返回。

    历史 bug: 这里原来扫 data/books/*.json,但 Phase 3a 之后书全在 SQLite 里,
    目录只剩空壳 —— 「预生成电子书音频」实际一次都没跑过,孩子每点一句
    都要现场等 edge-tts。修法: 和 books.py 同源,直接读 books 表。

    跨书重复的句子(常见: 同系列书里重复句型)只合成一次;
    >500 字符的跳过,与运行时路径的行为一致。
    """
    from extensions.db import get_db
    texts = {}  # dict 当有序 set 用,稳定输出顺序方便日志
    for row in get_db().execute('SELECT data_json FROM books').fetchall():
        try:
            book_data = json.loads(row['data_json'])
        except Exception as e:
            logger.warning(f'预生成跳过一本书 (data_json 解析失败): {e}')
            continue
        before = len(texts)
        for chapter in book_data.get('chapters', []):
            for sent in chapter.get('sentences', []):
                text = sent['text'] if isinstance(sent, dict) else sent
                if not text or len(text) > 500:
                    continue
                texts[text] = None
        logger.info(f"  {book_data.get('book', '?')[:40]}: 新增 {len(texts) - before} 句")
    return list(texts)


def pregenerate_all_tts():
    """预生成所有电子书和语法音频 (仅默认音色,避免启动时磁盘爆)。

    失败可见: _pregen_state.failed / last_error 由 /api/tts/status 暴露, 日志也写 warning。
    之前 except Exception: pass 静默, 预生成全挂也察觉不到。
    合成用 semaphore 收并发(见 _pregen_concurrency),单事件循环内跑,
    _pregen_state 的计数只在 await 间隙更新,无线程竞争。
    """
    if _pregen_state.get('running'):
        logger.info("TTS 预生成已在运行,跳过这次触发")
        return

    settings = tts_providers.get_settings()
    if settings['provider'] == 'device':
        # 家长选了「用平板自带语音」——服务端一个音频都不该合成,
        # 否则会白跑一遍几千条,还占几个 GB 磁盘。
        logger.info("TTS provider=device,跳过服务端预生成(前端用平板自带语音)")
        _pregen_state.update({'running': False, 'attempted': 0, 'succeeded': 0,
                              'failed': 0, 'last_error': None,
                              'skipped': 'device'})
        return

    async def generate():
        _pregen_state.update({'running': True, 'attempted': 0, 'succeeded': 0,
                              'failed': 0, 'last_error': None, 'skipped': None})
        try:
            TTS_DIR.mkdir(parents=True, exist_ok=True)

            # 1. 电子书句子 (从 SQLite 收集,全局去重)
            logger.info("正在预生成电子书音频...")
            texts = dict.fromkeys(_collect_pregen_texts())

            # 2. 语法讲解音频 (也进全局去重,书里可能恰好有同样的句子)
            logger.info("正在预生成语法讲解音频...")
            for grammar_text in GRAMMAR_EXPLANATIONS:
                texts.setdefault(grammar_text, None)

            concurrency = _pregen_concurrency()
            logger.info(f"共 {len(texts)} 段待合成, 并发 {concurrency}")
            sem = asyncio.Semaphore(concurrency)

            async def one(text):
                async with sem:
                    await _pregen_synthesize(text)

            await asyncio.gather(*(one(t) for t in texts))
        finally:
            _pregen_state['running'] = False
            logger.info(
                f"TTS 预生成完成: {_pregen_state['succeeded']}/{_pregen_state['attempted']} 成功, "
                f"{_pregen_state['failed']} 失败"
            )

    try:
        asyncio.run(generate())
    except Exception as e:
        logger.warning(f'Pre-generate error: {e}')
        _pregen_state['running'] = False


async def _pregen_synthesize(text: str) -> bool:
    """单条 TTS 合成 (预生成路径), 写 _pregen_state。

    提到模块级便于测试直接调 — 之前是 pregenerate_all_tts 内部闭包, 测不到。
    """
    settings = tts_providers.get_settings()
    voice = tts_providers.voice_for(settings)
    ext = tts_providers.audio_ext(settings)
    text_hash = _cache_key(text, voice, settings)
    audio_path = TTS_DIR / f'{text_hash}.{ext}'
    if audio_path.exists():
        _pregen_state['attempted'] += 1
        _pregen_state['succeeded'] += 1
        return True

    # 预生成是后台线程,不能阻塞。provider 合成是同步的(urllib / edge-tts),
    # 所以丢进线程池跑,别占住事件循环。
    def _synth():
        # 预生成是后台活,没人等着 —— 超时给得比「孩子点按钮」那条路宽。
        # 孩子点按钮时等 20 秒就该退回设备语音了,不能让人干等;
        # 但预生成这边等 45 秒只是多占一个后台线程,换来的是把
        # 微软那边慢的几百毫秒到几秒的请求也拿到好音色。
        pregen_settings = dict(settings)
        pregen_settings['timeout'] = max(int(settings.get('timeout') or 20), 45)
        data, _ext = tts_providers.synthesize(text, voice=voice, settings=pregen_settings)
        tmp = audio_path.with_name(f'.{audio_path.name}.{uuid.uuid4().hex}.tmp')
        try:
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, audio_path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    try:
        await asyncio.to_thread(_synth)
        _pregen_state['attempted'] += 1
        _pregen_state['succeeded'] += 1
        return True
    except Exception as e:
        _pregen_state['attempted'] += 1
        _pregen_state['failed'] += 1
        detail = e.detail if isinstance(e, tts_providers.TTSError) else f'{type(e).__name__}: {e}'
        _pregen_state['last_error'] = detail[:200]
        logger.warning(f'TTS 预生成失败: text={text[:30]!r} err={detail[:120]}')
        return False


GRAMMAR_EXPLANATIONS = [
    "Present Progressive: Subject plus am, is, are, plus verb-ing.",
    "This tense describes an action happening right now.",
    "Simple Present: Subject plus verb s or es.",
    "This tense describes habits and regular actions.",
    "Simple Past: Subject plus verb-ed.",
    "This tense describes actions that happened in the past.",
    "be going to: Subject plus am, is, are, going to plus verb.",
    "This expresses future plans.",
]


def start_tts_pregeneration():
    """由 app.py 在 __main__ 块显式调用,而非 import 时启动。"""
    t = threading.Thread(target=pregenerate_all_tts, name='tts-pregenerate', daemon=True)
    t.start()


def register_routes(app):
    @app.route('/api/tts', methods=['POST'])
    def text_to_speech():
        """TTS 语音合成 —— 引擎由家长在家长页配置(edge / 自建服务 / 平板自带)。

        缓存文件名里带 provider 指纹:换了引擎之后旧音频不会继续被命中,
        否则会出现「设置改了但读的 还是老声音」。
        """
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'tts')
        if not ok:
            return jsonify({
                "success": False,
                "error": f"请求过快, {retry} 秒后再试",
                "retryable": True,
                "retry_after": retry,
            }), 429

        data = request.get_json()
        text = data.get('text', '')
        voice = data.get('voice', '')

        if not text:
            return jsonify({
                "success": False,
                "error": "文本为空",
                "retryable": False,  # 用户输入问题, 重试也没用
                "retry_after": 0,
            })

        settings = tts_providers.get_settings()
        if settings['provider'] == 'device':
            # 家长选了「用平板自带语音」——服务端不合成,前端会直接用
            # speechSynthesis。这里返回明确指令而不是 500,免得前端以为是故障。
            return jsonify({
                "success": False,
                "error": "当前使用平板自带语音,服务端不合成",
                "use_device_voice": True,
                "retryable": False,
                "retry_after": 0,
            }), 409

        used_voice = tts_providers.voice_for(settings) if not voice else voice
        # 生成唯一文件名 (provider 指纹 + 音色 + 文本)
        text_hash = _cache_key(text, used_voice, settings)
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        ext = tts_providers.audio_ext(settings)
        audio_path = TTS_DIR / f'{text_hash}.{ext}'

        # 如果已存在:更新 atime (LRU 跟踪) + 直接返回
        if audio_path.exists():
            _touch_atime(audio_path)
            return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.{ext}"})

        temp_path = audio_path.with_name(f'.{audio_path.name}.{uuid.uuid4().hex}.tmp')

        try:
            audio, _ext = tts_providers.synthesize(text, voice=used_voice, settings=settings)
            with open(temp_path, 'wb') as f:
                f.write(audio)
            os.replace(temp_path, audio_path)
        except tts_providers.TTSError as e:
            # 原始异常进日志, 不暴露给前端 (可能含 token / path)
            logger.warning(f'TTS error: {e.detail}')
            return jsonify({
                "success": False,
                "error": e.message,
                "retryable": True,
                "retry_after": e.retry_after,
            }), e.http_status
        except Exception as e:
            logger.warning(f'TTS error: {type(e).__name__}: {e}')
            return jsonify({
                "success": False,
                "error": "语音合成失败, 请稍后再试",
                "retryable": True,
                "retry_after": 3,
            }), 502
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

        if audio_path.exists():
            # 异步触发 LRU 淘汰 (不阻塞响应)
            threading.Thread(target=_evict_tts_cache, args=(TTS_DIR,), name='tts-evict', daemon=True).start()
            return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.{ext}"})
        logger.warning(f'TTS 无音频: text={text[:30]!r}')
        return jsonify({
            "success": False,
            "error": "语音服务未返回音频, 请稍后再试",
            "retryable": True,
            "retry_after": 3,
        }), 502

    @app.route('/api/tts/status', methods=['GET'])
    def tts_status():
        """返回 TTS 缓存 + 预生成状态。

        前端轮询判断"系统是否准备好" (满足 tutor.html:967 的契约)。
        改名 + 改 GET: 之前叫 pregenerate 但只返回状态, 实际预生成是后台线程跑。
        限流 (R8): anon GET + 扫 100k 文件 glob 慢, 30/min 够家长按钮连点, 不够打 DoS。
        """
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'pregenerate')
        if not ok:
            return jsonify({
                "success": False,
                "error": f"请求过快, {retry} 秒后再试",
                "retryable": True,
                "retry_after": retry,
            }), 429
        files = _audio_files()
        count = len(files)
        size = sum(f.stat().st_size for f in files)
        settings = tts_providers.get_settings()
        return jsonify({
            "success": True,
            "status": "ok",
            "audio_files": count,
            "audio_bytes": size,
            "pregenerate": dict(_pregen_state),
            # device 模式下服务端不合成,预生成统计没有意义,前端据此隐藏进度。
            "provider": settings['provider'],
            "server_synthesis": settings['provider'] != 'device',
        })

    # === TTS 设置(家长配置) ===
    # 读接口公开(孩子端要知道该不该调 /api/tts),但**只返回不含密钥的摘要**。
    # 写接口必须家长登录。
    @app.route('/api/tts/settings', methods=['GET'])
    def tts_settings_get():
        """孩子端和家长端共用一个 GET。

        分成两个同路径的 GET 是没用的 —— Flask 只会命中先注册的那个,
        家长视图将永远取不到。公开字段(能不能调服务端合成)人人都能看;
        家长额外拿端点/模型/格式。
        """
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'tts_settings')
        if not ok:
            return jsonify({"success": False, "error": "请求过快", "retry_after": retry}), 429
        data = {"success": True, **tts_providers.public_settings()}
        if session.get('parent_auth'):
            data["settings"] = tts_providers.parent_settings_view()
        return jsonify(data)

    @app.route('/api/tts/settings', methods=['POST'])
    @require_parent_auth
    def tts_settings_save():
        """保存设置。api_key 传空字符串 = 清空密钥(用整段覆盖而不是增量合并,
        否则家长在表单里删掉密钥会存不进去)。"""
        body = request.get_json(silent=True) or {}
        try:
            tts_providers.save_settings(body)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error('TTS 设置保存失败: %s', e)
            return jsonify({"success": False, "error": '保存失败'}), 500
        # 这里**不**自动开一轮全量预生成:
        #   - 家长刚换引擎时最想干的是「听一句」,那是 /api/tts/test 的事;
        #   - 几千条全量合成会立刻把家里那台 TTS 服务打满,还可能刷屏报错;
        #   - 连按两次保存会起两个预生成线程互相踩 _pregen_state。
        # 想整本预生成,跟读页点「预下载音频」。
        return jsonify({"success": True, "settings": tts_providers.parent_settings_view()})

    @app.route('/api/tts/pregenerate', methods=['POST'])
    def tts_pregenerate():
        """启动一轮后台预生成,立即返回。

        跟读页的「预下载音频」按钮调的就是这个。之前**这个路由根本不存在**
        (前端调了,后端 404),按钮点了只会报错。
        """
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'pregenerate')
        if not ok:
            return jsonify({
                "success": False,
                "error": f"请求过快, {retry} 秒后再试",
                "retryable": True,
                "retry_after": retry,
            }), 429

        settings = tts_providers.get_settings()
        if settings['provider'] == 'device':
            return jsonify({
                "success": False,
                "error": "当前使用平板自带语音,服务端不生成音频",
            }), 409
        if _pregen_state.get('running'):
            return jsonify({
                "success": True,
                "error": "已经在生成了",
                "pregenerate": dict(_pregen_state),
            })
        threading.Thread(target=pregenerate_all_tts, name='tts-pregenerate', daemon=True).start()
        return jsonify({"success": True, "pregenerate": dict(_pregen_state)})

    @app.route('/api/tts/cache', methods=['POST'])
    @require_parent_auth
    def tts_cache_clear():
        """清空服务端音频缓存。

        换引擎之后旧音频是**孤儿**:缓存 key 带了 provider 指纹,永远不会再被命中,
        但文件还占着磁盘(预生成过的书能有几个 GB)。换引擎之后清一次是合理动作。
        """
        removed, freed = 0, 0
        if TTS_DIR.exists():
            for f in list(TTS_DIR.iterdir()):
                try:
                    if f.is_file():
                        freed += f.stat().st_size
                        f.unlink()
                        removed += 1
                except OSError:
                    pass
        logger.info(f'TTS 缓存已清空: {removed} 个文件 / {freed / 1048576:.1f} MB')
        return jsonify({"success": True, "removed": removed, "freed_bytes": freed})

    @app.route('/api/tts/settings/clear-key', methods=['POST'])
    @require_parent_auth
    def tts_settings_clear_key():
        tts_providers.clear_api_key()
        return jsonify({"success": True, "settings": tts_providers.parent_settings_view()})

    @app.route('/api/tts/settings', methods=['DELETE'])
    @require_parent_auth
    def tts_settings_reset():
        tts_providers.clear_settings()
        return jsonify({"success": True, "settings": tts_providers.parent_settings_view()})

    @app.route('/api/tts/test', methods=['POST'])
    @require_parent_auth
    def tts_test():
        """试听:合成一句短文本,返回耗时和体积。

        家长手填端点/密钥时最需要的就是「到底通没通、哪里错了」,
        所以失败必须带可读原因(地址错 / 密钥错 / 接口不存在),不是抛栈。
        """
        body = request.get_json(silent=True) or {}
        # 允许试听「表单里还没保存的草稿」:点了就听见,不用先保存再试。
        draft = {k: v for k, v in body.items() if k in tts_providers.DEFAULTS}
        if draft:
            base = tts_providers.get_settings()
            base.update({k: v for k, v in draft.items() if v not in (None, '')})
            if 'api_key' in body:
                base['api_key'] = body['api_key']
            settings = base
        else:
            settings = tts_providers.get_settings()
        result = tts_providers.check_connection(settings, with_audio=True)
        code = 200 if result['success'] else 502
        if result['success']:
            logger.info('TTS 试听成功: %sms %sB', result['ms'], result['bytes'])
        else:
            logger.warning('TTS 试听失败: %s', result.get('detail'))
        return jsonify(result), code

    @app.route('/audio/<path:filename>')
    def serve_audio(filename):
        """提供音频文件 (audio/tts/* 和 audio/* 通用)"""
        # LRU 跟踪:每次 GET 都更新 atime,让真正常用的 mp3 不会被淘汰
        full_path = AUDIO_ROOT / filename
        # 防止路径穿越 (虽然 send_from_directory 已经做了)
        try:
            if full_path.resolve().is_relative_to(AUDIO_ROOT.resolve()) and full_path.exists():
                _touch_atime(full_path)
        except (OSError, ValueError):
            pass
        return send_from_directory(str(AUDIO_ROOT), filename)
