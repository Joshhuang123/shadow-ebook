"""TTS 预生成的书源必须是 SQLite,而不是 data/books/*.json。

历史 bug: Phase 3a 把书迁进 SQLite 后,预生成还在扫 data/books/*.json ——
迁移完成时原文件已挪进 data/books.migrated-<ts>/,目录只剩空壳。
于是「预生成电子书音频」一次都没真正跑过,孩子每点一句都要现场等
edge-tts (1s+),阅读体验卡顿,而且没人发现 —— 后台线程不报错。

顺带的第二个问题: 预生成是逐句 await,一本 800 句的书要 10+ 分钟,
孩子早开读了。现在用 semaphore 收并发(默认 4),缩短到分钟级。

本文件钉住三件事:
  1. DB 里的书句真的被送去合成
  2. 跨书重复的句子只合成一次
  3. >500 字符的句子跳过 (与运行时路径行为一致)
"""
import json
from pathlib import Path

import pytest

from extensions import db, tts


@pytest.fixture
def tts_dir(tmp_path, monkeypatch):
    d = tmp_path / 'tts'
    monkeypatch.setattr(tts, 'TTS_DIR', d)
    return d


@pytest.fixture
def books_in_db(tmp_db):
    """两本书: 共享 1 个重复句 + 各自独有句子 + 1 条超长句(应跳过)。"""
    shared = 'The cat sat on the mat and looked at the rain.'
    book_a = {
        'book': 'Book A',
        'chapters': [{'name': 'c1', 'sentences': [
            shared,
            'This is a unique sentence that only appears in book A.',
        ]}],
    }
    book_b = {
        'book': 'Book B',
        'chapters': [{'name': 'c1', 'sentences': [
            shared,
            'Another sentence that lives only inside book B here.',
            'x' * 501,   # 超长,预生成必须跳过
        ]}],
    }
    now = 0
    conn = db.get_db()
    for bid, data in (('book_a', book_a), ('book_b', book_b)):
        conn.execute(
            'INSERT OR REPLACE INTO books (id, data_json, imported_at, updated_at) '
            'VALUES (?, ?, ?, ?)',
            (bid, json.dumps(data, ensure_ascii=False), now, now),
        )
    return {'shared': shared, 'a': book_a, 'b': book_b}


@pytest.fixture
def synth_log(monkeypatch):
    """FakeComm 记录每次真实合成的 text;命中缓存的文件不经过它。"""
    calls = []

    class FakeComm:
        def __init__(self, text, voice):
            self.text = text

        async def save(self, path):
            calls.append(self.text)
            Path(path).write_bytes(b'fake-mp3')

    monkeypatch.setattr('extensions.tts.edge_tts.Communicate', FakeComm)
    return calls


@pytest.fixture(autouse=True)
def reset_pregen_state():
    tts._pregen_state.update(
        {'running': False, 'attempted': 0, 'succeeded': 0, 'failed': 0, 'last_error': None})
    yield


def test_pregen_synthesizes_sentences_from_db(books_in_db, tts_dir, synth_log):
    tts.pregenerate_all_tts()

    all_texts = set(synth_log)
    for sent in ('This is a unique sentence that only appears in book A.',
                 'Another sentence that lives only inside book B here.'):
        assert sent in all_texts, f'DB 里的句子没被预生成: {sent}'


def test_pregen_dedupes_across_books(books_in_db, tts_dir, synth_log):
    """同一句在两本书里都出现 → 只合成一次(第二次走缓存命中路径)。"""
    tts.pregenerate_all_tts()
    assert synth_log.count(books_in_db['shared']) == 1


def test_pregen_skips_overlong_sentences(books_in_db, tts_dir, synth_log):
    tts.pregenerate_all_tts()
    assert 'x' * 501 not in set(synth_log)


def test_pregen_covers_grammar_explanations(books_in_db, tts_dir, synth_log):
    tts.pregenerate_all_tts()
    for g in tts.GRAMMAR_EXPLANATIONS:
        assert g in set(synth_log), f'语法讲解没被预生成: {g[:40]}'


def test_pregen_state_counts_add_up(books_in_db, tts_dir, synth_log):
    """attempted = succeeded + failed,且 failed=0 时全绿。"""
    tts.pregenerate_all_tts()
    st = tts._pregen_state
    assert st['running'] is False
    assert st['attempted'] == st['succeeded'] + st['failed']
    assert st['failed'] == 0
    # 真实合成的次数 = attempted - 缓存命中数;至少 DB 的独有句子都试过
    assert st['attempted'] >= 5  # 3 个独有句 + 8 条语法讲解 - 重复句缓存命中


def test_pregen_existing_files_are_not_regenerated(books_in_db, tts_dir, synth_log):
    """跑过一遍后再跑,全部命中缓存,edge_tts 一次都不该被调。"""
    tts.pregenerate_all_tts()
    first_run = list(synth_log)
    assert first_run, '第一轮就该有真实合成'

    synth_log.clear()
    tts.pregenerate_all_tts()
    assert synth_log == [], '缓存已存在的音频不该重新合成'


def test_pregen_concurrency_env_override(monkeypatch):
    monkeypatch.setattr(tts, '_PREGEN_CONCURRENCY_DEFAULT', 4)
    monkeypatch.setenv('SHADOW_TTS_PREGEN_CONCURRENCY', '9')
    assert tts._pregen_concurrency() == 9
    monkeypatch.setenv('SHADOW_TTS_PREGEN_CONCURRENCY', '999')
    assert tts._pregen_concurrency() == 16   # 封顶
    monkeypatch.setenv('SHADOW_TTS_PREGEN_CONCURRENCY', 'abc')
    assert tts._pregen_concurrency() == 4    # 非法值回默认
    monkeypatch.setenv('SHADOW_TTS_PREGEN_CONCURRENCY', '')
    assert tts._pregen_concurrency() == 4
