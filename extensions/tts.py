"""
Owns: TTS endpoint, TTS cache eviction policy (LRU via atime), TTS pregeneration background task,
audio file serving, /api/tts/pregenerate status endpoint.
Does NOT own: course content (courses.py), book content (books.py), auth/rate-limit helpers (auth.py).
"""
import asyncio
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from flask import jsonify, request, send_from_directory

from extensions.auth import _api_rate_limit_ok


logger = logging.getLogger(__name__)


TTS_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
TTS_CACHE_MAX_FILES = 100_000
AUDIO_ROOT = Path(__file__).resolve().parent.parent / 'audio'
TTS_DIR = AUDIO_ROOT / 'tts'


# === TTS 缓存淘汰 (真正的 LRU: 基于 atime, mtime 不可靠) ===
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
def pregenerate_all_tts():
    """预生成所有电子书和语法音频 (仅默认音色,避免启动时磁盘爆)"""
    import edge_tts

    VOICES = ['en-US-AriaNeural']

    GRAMMAR_EXPLAINATIONS = [
        "Present Progressive: Subject plus am, is, are, plus verb-ing.",
        "This tense describes an action happening right now.",
        "Simple Present: Subject plus verb s or es.",
        "This tense describes habits and regular actions.",
        "Simple Past: Subject plus verb-ed.",
        "This tense describes actions that happened in the past.",
        "be going to: Subject plus am, is, are, going to plus verb.",
        "This expresses future plans.",
    ]

    async def generate():
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        books_dir = Path(__file__).resolve().parent.parent / 'data' / 'books'

        # 1. 遍历所有电子书
        logger.info("正在预生成电子书音频...")
        for book_file in books_dir.glob('*.json'):
            try:
                book_data = json.loads(book_file.read_text())
                sentences_count = 0
                for chapter in book_data.get("chapters", []):
                    for sent in chapter.get("sentences", []):
                        text = sent["text"] if isinstance(sent, dict) else sent
                        if not text or len(text) > 500:
                            continue
                        sentences_count += 1
                        for voice in VOICES:
                            text_hash = hashlib.md5((text + voice).encode()).hexdigest()[:12]
                            audio_path = TTS_DIR / f'{text_hash}.mp3'
                            if not audio_path.exists():
                                try:
                                    await edge_tts.Communicate(text, voice=voice).save(str(audio_path))
                                except Exception:
                                    pass
                logger.info(f"  {book_data.get('book', book_file.stem)[:40]}: {sentences_count}句")
            except Exception as e:
                logger.warning(f"  {book_file}: {e}")

        # 2. 生成语法讲解音频
        logger.info("正在预生成语法讲解音频...")
        for grammar_text in GRAMMAR_EXPLAINATIONS:
            for voice in VOICES:
                text_hash = hashlib.md5((grammar_text + voice).encode()).hexdigest()[:12]
                audio_path = TTS_DIR / f'{text_hash}.mp3'
                if not audio_path.exists():
                    try:
                        await edge_tts.Communicate(grammar_text, voice=voice).save(str(audio_path))
                    except Exception:
                        pass
        logger.info("所有TTS音频预生成完成")

    try:
        asyncio.run(generate())
    except Exception as e:
        logger.warning(f"Pre-generate error: {e}")


def start_tts_pregeneration():
    """由 app.py 在 __main__ 块显式调用,而非 import 时启动。"""
    t = threading.Thread(target=pregenerate_all_tts, daemon=True)
    t.start()


TTS_TIMEOUT_SEC = 15  # edge-tts 卡死时 worker 也不能无限等


def register_routes(app):
    @app.route('/api/tts', methods=['POST'])
    def text_to_speech():
        """TTS 语音合成 - 使用 edge-tts, 缓存到本地"""
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
        voice = data.get('voice', 'en-US-AriaNeural')  # 默认 Aria

        if not text:
            return jsonify({
                "success": False,
                "error": "文本为空",
                "retryable": False,  # 用户输入问题, 重试也没用
                "retry_after": 0,
            })
        # 生成唯一文件名 (包含音色的 hash)
        text_hash = hashlib.md5((text + voice).encode()).hexdigest()[:12]
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        audio_path = TTS_DIR / f'{text_hash}.mp3'

        # 如果已存在:更新 atime (LRU 跟踪) + 直接返回
        if audio_path.exists():
            _touch_atime(audio_path)
            return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})

        import edge_tts

        async def generate():
            # 加 15s 超时: 网络抖动时 edge-tts 可能挂 30s+, 拖死整个 worker
            await asyncio.wait_for(
                edge_tts.Communicate(text, voice=voice).save(str(audio_path)),
                timeout=TTS_TIMEOUT_SEC,
            )

        try:
            asyncio.run(generate())
        except asyncio.TimeoutError:
            logger.warning(f'TTS 超时 ({TTS_TIMEOUT_SEC}s): text={text[:30]!r}')
            return jsonify({
                "success": False,
                "error": "语音合成超时, 请稍后再试",
                "retryable": True,
                "retry_after": 5,
            }), 504
        except Exception as e:
            # 原始异常进日志, 不暴露给前端 (可能含 token / path)
            logger.warning(f'TTS error: {type(e).__name__}: {e}')
            return jsonify({
                "success": False,
                "error": "语音合成失败, 请稍后再试",
                "retryable": True,
                "retry_after": 3,
            }), 502

        if audio_path.exists():
            # 异步触发 LRU 淘汰 (不阻塞响应)
            threading.Thread(target=_evict_tts_cache, args=(TTS_DIR,), daemon=True).start()
            return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})
        # edge-tts 没抛异常但也没写出文件 — 服务端静默失败
        logger.warning(f'TTS 无音频: text={text[:30]!r}')
        return jsonify({
            "success": False,
            "error": "语音服务未返回音频, 请稍后再试",
            "retryable": True,
            "retry_after": 3,
        }), 502

    @app.route('/api/tts/pregenerate', methods=['POST'])
    def pregenerate_status():
        """前端调,返回当前 TTS 缓存状态 (满足 tutor.html:967 的契约)。

        实际预生成由后台线程在启动时跑;此 endpoint 主要返回状态。
        """
        count = sum(1 for _ in TTS_DIR.glob('*.mp3')) if TTS_DIR.exists() else 0
        return jsonify({"success": True, "status": "ok", "audio_files": count})

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