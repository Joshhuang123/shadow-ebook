"""TTS 缓存淘汰: 真正的 LRU (基于 atime), 0 字节优先, max_files 也触发, 单遍迭代不漏删。

历史 bug: _evict_tts_cache 用 `entries.remove(...)` 同时迭代 entries,
导致每次循环跳过下一项 (Python 列表 mutation 陷阱), 实际只删一半。
本文件守住这个 bug 不回来。
"""
import os
import time
from pathlib import Path

from extensions import tts


def _make_mp3(path: Path, size: int, atime_offset_sec: float = 0):
    """造一个指定大小+atime 的假 mp3。atime_offset_sec 越大越旧。"""
    path.write_bytes(b'\x00' * size)
    if atime_offset_sec:
        old = time.time() - atime_offset_sec
        os.utime(path, (old, old))


def test_evict_drops_oldest_atime_first(tmp_path, monkeypatch):
    """超过 max_bytes 时, atime 最老的先删 (LRU 核心语义)"""
    audio = tmp_path / 'tts'
    audio.mkdir()
    for i in range(5):
        f = audio / f'voice_{i}.mp3'
        _make_mp3(f, size=200, atime_offset_sec=(5 - i) * 60)  # i=0 最老

    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_BYTES', 500)   # 容 2 个 200B 文件
    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_FILES', 100)
    tts._evict_tts_cache(audio)

    remaining = sorted(p.name for p in audio.glob('*.mp3'))
    # 最老的 3 个 (voice_0, voice_1, voice_2) 该被删, voice_3 / voice_4 留
    assert remaining == ['voice_3.mp3', 'voice_4.mp3']


def test_evict_zero_byte_first(tmp_path, monkeypatch):
    """0 字节残留 (上次生成失败) 优先删, 不论 atime"""
    audio = tmp_path / 'tts'
    audio.mkdir()
    z = audio / 'zero.mp3'
    z.write_bytes(b'')  # 0 字节, atime 最新
    full = audio / 'full.mp3'
    _make_mp3(full, size=500, atime_offset_sec=3600)  # 1 小时前, 应保留

    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_BYTES', 10_000)
    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_FILES', 100)
    tts._evict_tts_cache(audio)

    remaining = sorted(p.name for p in audio.glob('*.mp3'))
    assert remaining == ['full.mp3']


def test_evict_under_limit_does_nothing(tmp_path, monkeypatch):
    """没超限制, 一个都不该删"""
    audio = tmp_path / 'tts'
    audio.mkdir()
    for i in range(3):
        _make_mp3(audio / f'voice_{i}.mp3', size=200)

    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_BYTES', 10_000)
    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_FILES', 100)
    tts._evict_tts_cache(audio)

    assert len(list(audio.glob('*.mp3'))) == 3


def test_evict_max_files_triggers(tmp_path, monkeypatch):
    """max_files 超也触发淘汰 (即使 bytes 没超)"""
    audio = tmp_path / 'tts'
    audio.mkdir()
    for i in range(5):
        _make_mp3(audio / f'voice_{i}.mp3', size=10, atime_offset_sec=(5 - i) * 60)

    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_BYTES', 1_000_000)
    monkeypatch.setattr(tts, 'TTS_CACHE_MAX_FILES', 2)
    tts._evict_tts_cache(audio)

    remaining = sorted(p.name for p in audio.glob('*.mp3'))
    assert remaining == ['voice_3.mp3', 'voice_4.mp3']


def test_evict_missing_dir_does_nothing(tmp_path):
    """目录不存在, 静默返回不抛"""
    nonexistent = tmp_path / 'nope'
    # 不该报错
    tts._evict_tts_cache(nonexistent)
