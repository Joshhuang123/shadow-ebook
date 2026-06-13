"""
Owns: TTS endpoint, TTS cache eviction policy, TTS pregeneration background task, audio file serving.
Does NOT own: course content (courses.py), book content (books.py), auth/rate-limit helpers (auth.py).
"""
import asyncio
import hashlib
import json
import threading
from pathlib import Path
from flask import jsonify, request, send_from_directory

from extensions.auth import _api_rate_limit_ok


TTS_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
TTS_CACHE_MAX_FILES = 100_000
AUDIO_ROOT = Path(__file__).resolve().parent.parent / 'audio'
TTS_DIR = AUDIO_ROOT / 'tts'


# === TTS 缓存淘汰 ===
def _evict_tts_cache(audio_dir: Path):
    """超过 TTS_CACHE_MAX_BYTES / TTS_CACHE_MAX_FILES 时,按 mtime 删最旧文件。

    注意: 用的是 mtime (modify time),不是真正的 atime (access time)。
    Phase 2 会改成真正的 LRU: read/write 时 os.utime 更新 atime,evict 按 atime 排。
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
            entries.append((f, st.st_mtime, st.st_size))

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

        # 按 mtime 升序排 (最旧在前)
        entries.sort(key=lambda e: e[1])

        for f, _, sz in entries:
            if total_bytes <= TTS_CACHE_MAX_BYTES and len(entries) <= TTS_CACHE_MAX_FILES:
                break
            try:
                f.unlink()
                total_bytes -= sz
                entries.remove((f, _, sz))
                evicted_count += 1
            except OSError:
                pass

        if evicted_count:
            print(f"🗑️  TTS 缓存淘汰: 删除 {evicted_count} 个最旧文件, 剩余 {len(entries)} 个 / {total_bytes // (1024*1024)}MB")
    except Exception as e:
        print(f"TTS cache evict error: {e}")


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
        print("📚 正在预生成电子书音频...")
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
                print(f"  ✅ {book_data.get('book', book_file.stem)[:40]}: {sentences_count}句")
            except Exception as e:
                print(f"  ❌ {book_file}: {e}")

        # 2. 生成语法讲解音频
        print("📝 正在预生成语法讲解音频...")
        for grammar_text in GRAMMAR_EXPLAINATIONS:
            for voice in VOICES:
                text_hash = hashlib.md5((grammar_text + voice).encode()).hexdigest()[:12]
                audio_path = TTS_DIR / f'{text_hash}.mp3'
                if not audio_path.exists():
                    try:
                        await edge_tts.Communicate(grammar_text, voice=voice).save(str(audio_path))
                    except Exception:
                        pass
        print("🎉 所有TTS音频预生成完成！")

    try:
        asyncio.run(generate())
    except Exception as e:
        print(f"Pre-generate error: {e}")


def start_tts_pregeneration():
    """由 app.py 在 __main__ 块显式调用,而非 import 时启动。"""
    t = threading.Thread(target=pregenerate_all_tts, daemon=True)
    t.start()


def register_routes(app):
    @app.route('/api/tts', methods=['POST'])
    def text_to_speech():
        """TTS 语音合成 - 使用 edge-tts, 缓存到本地"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'tts')
        if not ok:
            return jsonify({"success": False, "error": f"请求过快, {retry} 秒后再试"}), 429

        data = request.get_json()
        text = data.get('text', '')
        voice = data.get('voice', 'en-US-AriaNeural')  # 默认 Aria

        if not text:
            return jsonify({"success": False, "error": "文本为空"})
        # 生成唯一文件名 (包含音色的 hash)
        text_hash = hashlib.md5((text + voice).encode()).hexdigest()[:12]
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        audio_path = TTS_DIR / f'{text_hash}.mp3'

        # 如果已存在则直接返回
        if audio_path.exists():
            return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})

        import edge_tts

        async def generate():
            try:
                await edge_tts.Communicate(text, voice=voice).save(str(audio_path))
                return True
            except Exception as e:
                print(f"TTS error: {e}")
                return False

        try:
            asyncio.run(generate())
        except Exception as e:
            return jsonify({"success": False, "error": f"TTS生成失败: {str(e)}"})

        if audio_path.exists():
            # 异步触发 LRU 淘汰 (不阻塞响应)
            threading.Thread(target=_evict_tts_cache, args=(TTS_DIR,), daemon=True).start()
            return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})
        return jsonify({"success": False, "error": "TTS生成失败"})

    @app.route('/audio/<path:filename>')
    def serve_audio(filename):
        """提供音频文件 (audio/tts/* 和 audio/* 通用)"""
        return send_from_directory(str(AUDIO_ROOT), filename)