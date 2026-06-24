"""R12: 间隔重复 (SRS) 状态机 + 端点测试。

覆盖:
- _srs_next_state 答对/答错转移
- _record_vocab_lookup 老词不重置
- _record_vocab_review 推进状态
- _get_due_reviews 按 next_review_ts 排序
- _vocab_state_counts 4 桶 + due_now
- calc_sentence_mastery 时长比例判定
- /api/vocab/{lookup,review,review-queue,stats} 端点
- /api/progress /api/sentence/mastery 端点
"""
import importlib
import time

import pytest

from extensions import parent_data


@pytest.fixture
def client(tmp_db, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


# === SRS 状态机单测 ===
def test_srs_next_state_correct_promotes():
    assert parent_data._srs_next_state('learning', True) == 'practicing'
    assert parent_data._srs_next_state('practicing', True) == 'familiar'
    assert parent_data._srs_next_state('familiar', True) == 'mastered'
    # mastered 答对保持
    assert parent_data._srs_next_state('mastered', True) == 'mastered'


def test_srs_next_state_wrong_demotes():
    assert parent_data._srs_next_state('mastered', False) == 'familiar'
    assert parent_data._srs_next_state('familiar', False) == 'practicing'
    assert parent_data._srs_next_state('practicing', False) == 'learning'
    # learning 答错保持
    assert parent_data._srs_next_state('learning', False) == 'learning'


def test_srs_interval_ms():
    assert parent_data._srs_interval_ms('learning') == 0  # 立即复习
    assert parent_data._srs_interval_ms('practicing') == 2 * 86400 * 1000
    assert parent_data._srs_interval_ms('familiar') == 5 * 86400 * 1000
    assert parent_data._srs_interval_ms('mastered') == 14 * 86400 * 1000


# === _record_vocab_lookup ===
def test_lookup_creates_learning_entry(tmp_db):
    r = parent_data._record_vocab_lookup('apple')
    assert r['state'] == 'learning'
    assert r['review_count'] == 0
    # learning 间隔 = 0, 所以 next_review_ts 就是 now (立即复习)
    assert r['next_review_ts'] <= int(time.time() * 1000)


def test_lookup_old_word_does_not_reset(tmp_db):
    parent_data._record_vocab_lookup('apple')
    parent_data._record_vocab_review('apple', correct=True)  # → practicing
    r_before = parent_data._record_vocab_lookup('apple')  # 再查一次
    assert r_before['state'] == 'practicing', '老词 lookup 不该重置状态'
    assert r_before['review_count'] == 1, '老词 lookup 不该重置计数'


def test_lookup_empty_word_returns_empty(tmp_db):
    assert parent_data._record_vocab_lookup('') == {}
    assert parent_data._record_vocab_lookup('   ') == {}


def test_lookup_marks_looked_words(tmp_db):
    parent_data._record_vocab_lookup('Banana')  # 大写
    data = parent_data._load_parent_data()
    assert data['vocabulary']['lookedWords'].get('banana') is True


# === _record_vocab_review ===
def test_review_promotes_on_correct(tmp_db):
    parent_data._record_vocab_lookup('cat')
    r = parent_data._record_vocab_review('cat', correct=True)
    assert r['state'] == 'practicing'
    assert r['review_count'] == 1
    assert r['correct_count'] == 1
    assert r['last_review_ts'] is not None


def test_review_demotes_on_wrong(tmp_db):
    parent_data._record_vocab_lookup('dog')
    parent_data._record_vocab_review('dog', correct=True)  # → practicing
    r = parent_data._record_vocab_review('dog', correct=False)
    assert r['state'] == 'learning', 'practicing 答错 → learning'
    assert r['review_count'] == 2
    assert r['correct_count'] == 1, 'correct_count 只数对的不数错的'


def test_review_nonexistent_word_returns_none(tmp_db):
    assert parent_data._record_vocab_review('unknown', True) is None


# === _get_due_reviews ===
def test_due_reviews_excludes_future(tmp_db):
    parent_data._record_vocab_lookup('soon')
    parent_data._record_vocab_lookup('now')
    # 手动把 'soon' 推到远未来
    data = parent_data._load_parent_data()
    data['vocabReviews']['soon']['next_review_ts'] = int(time.time() * 1000) + 99999999
    parent_data._save_parent_data(data)
    due = parent_data._get_due_reviews()
    words = [w for w, _ in due]
    assert 'now' in words
    assert 'soon' not in words


def test_due_reviews_sorted_by_next_review(tmp_db):
    parent_data._record_vocab_lookup('a')
    parent_data._record_vocab_lookup('b')
    data = parent_data._load_parent_data()
    now = int(time.time() * 1000)
    data['vocabReviews']['a']['next_review_ts'] = now - 100
    data['vocabReviews']['b']['next_review_ts'] = now - 50
    parent_data._save_parent_data(data)
    due = parent_data._get_due_reviews()
    assert due[0][0] == 'a', '到期更早的应在前'


def test_due_reviews_respects_limit(tmp_db):
    for w in ['w1', 'w2', 'w3', 'w4', 'w5']:
        parent_data._record_vocab_lookup(w)
    assert len(parent_data._get_due_reviews(limit=3)) == 3


# === _vocab_state_counts ===
def test_state_counts_distribution(tmp_db):
    for w in ['a', 'b']:
        parent_data._record_vocab_lookup(w)  # learning
    parent_data._record_vocab_lookup('c')
    parent_data._record_vocab_review('c', True)  # practicing
    parent_data._record_vocab_lookup('d')
    parent_data._record_vocab_review('d', True)
    parent_data._record_vocab_review('d', True)  # familiar

    counts = parent_data._vocab_state_counts()
    assert counts['learning'] == 2
    assert counts['practicing'] == 1
    assert counts['familiar'] == 1
    assert counts['mastered'] == 0
    assert counts['total'] == 4
    # a + b 是 learning (0d 间隔), 立刻到期 = 2
    # c → practicing (2d), d → familiar (5d) 都不到期
    assert counts['due_now'] == 2


# === calc_sentence_mastery ===
def test_mastery_too_short_is_attempted():
    assert parent_data.calc_sentence_mastery(2.0, 0.5) == 'attempted'
    assert parent_data.calc_sentence_mastery(2.0, 0.9) == 'attempted'  # < 0.5x = 1.0


def test_mastery_close_to_original_is_fluent():
    assert parent_data.calc_sentence_mastery(2.0, 1.6) == 'fluent'  # 0.8x
    assert parent_data.calc_sentence_mastery(2.0, 2.0) == 'fluent'  # 1.0x
    assert parent_data.calc_sentence_mastery(2.0, 2.4) == 'fluent'  # 1.2x


def test_mastery_too_long_is_slow():
    assert parent_data.calc_sentence_mastery(2.0, 3.0) == 'slow'  # 1.5x
    assert parent_data.calc_sentence_mastery(2.0, 5.0) == 'slow'


def test_mastery_zero_returns_attempted():
    assert parent_data.calc_sentence_mastery(0, 1.0) == 'attempted'
    assert parent_data.calc_sentence_mastery(1.0, 0) == 'attempted'


# === /api/vocab/lookup 端点 ===
def test_lookup_endpoint(tmp_db, client):
    r = client.post('/api/vocab/lookup', json={'word': 'apple'})
    assert r.status_code == 200
    assert r.json['success'] is True
    assert r.json['review']['state'] == 'learning'


def test_lookup_endpoint_empty_word(client):
    r = client.post('/api/vocab/lookup', json={'word': ''})
    assert r.status_code == 200
    assert r.json['success'] is False


# === /api/vocab/review 端点 ===
def test_review_endpoint_promotes(tmp_db, client):
    client.post('/api/vocab/lookup', json={'word': 'cat'})
    r = client.post('/api/vocab/review', json={'word': 'cat', 'correct': True})
    assert r.json['success'] is True
    assert r.json['review']['state'] == 'practicing'


def test_review_endpoint_unknown_word(client):
    r = client.post('/api/vocab/review', json={'word': 'nope', 'correct': True})
    assert r.status_code == 404


# === /api/vocab/review-queue 端点 ===
def test_review_queue_endpoint(tmp_db, client):
    client.post('/api/vocab/lookup', json={'word': 'a'})
    client.post('/api/vocab/lookup', json={'word': 'b'})
    r = client.get('/api/vocab/review-queue')
    assert r.status_code == 200
    assert r.json['success'] is True
    assert len(r.json['queue']) == 2


def test_review_queue_respects_limit(tmp_db, client):
    for w in ['w1', 'w2', 'w3', 'w4', 'w5']:
        client.post('/api/vocab/lookup', json={'word': w})
    r = client.get('/api/vocab/review-queue?limit=2')
    assert len(r.json['queue']) == 2


# === /api/vocab/stats 端点 ===
def test_stats_endpoint(tmp_db, client):
    client.post('/api/vocab/lookup', json={'word': 'a'})
    client.post('/api/vocab/lookup', json={'word': 'b'})
    client.post('/api/vocab/lookup', json={'word': 'c'})
    client.post('/api/vocab/review', json={'word': 'c', 'correct': True})  # practicing
    r = client.get('/api/vocab/stats')
    assert r.json['learning'] == 2
    assert r.json['practicing'] == 1
    assert r.json['total'] == 3


# === /api/progress 端点 ===
def test_progress_save_and_get(tmp_db, client):
    r = client.post('/api/progress', json={'bookId': 'hp1', 'chapterIdx': 2, 'sentenceIdx': 5})
    assert r.json['success'] is True
    assert r.json['progress']['chapter_idx'] == 2
    assert r.json['progress']['sentence_idx'] == 5

    r = client.get('/api/progress/hp1')
    assert r.json['progress']['chapter_idx'] == 2
    assert r.json['progress']['sentence_idx'] == 5


def test_progress_get_unknown_book(client):
    r = client.get('/api/progress/unknown')
    assert r.json['progress'] is None


def test_progress_all(tmp_db, client):
    client.post('/api/progress', json={'bookId': 'a', 'chapterIdx': 1, 'sentenceIdx': 0})
    client.post('/api/progress', json={'bookId': 'b', 'chapterIdx': 0, 'sentenceIdx': 3})
    r = client.get('/api/progress')
    assert 'a' in r.json['progress']
    assert 'b' in r.json['progress']


def test_progress_save_validates_input(client):
    r = client.post('/api/progress', json={'bookId': '', 'chapterIdx': 0, 'sentenceIdx': 0})
    assert r.json['success'] is False
    r = client.post('/api/progress', json={'bookId': 'a', 'chapterIdx': 'x', 'sentenceIdx': 0})
    assert r.json['success'] is False


# === /api/sentence/mastery 端点 ===
def test_mastery_save_and_get(tmp_db, client):
    r = client.post('/api/sentence/mastery', json={
        'bookId': 'hp1', 'chapterIdx': 0, 'sentenceIdx': 3, 'mastery': 'fluent',
    })
    assert r.json['success'] is True
    assert r.json['mastery']['mastery'] == 'fluent'

    r = client.get('/api/sentence/mastery/hp1')
    assert r.json['mastery']['0']['3']['mastery'] == 'fluent'


def test_mastery_fluent_not_overwritten_by_slow(tmp_db, client):
    """fluent 不被 slow 覆盖 (录音抖动防御)"""
    client.post('/api/sentence/mastery', json={
        'bookId': 'a', 'chapterIdx': 0, 'sentenceIdx': 0, 'mastery': 'fluent',
    })
    client.post('/api/sentence/mastery', json={
        'bookId': 'a', 'chapterIdx': 0, 'sentenceIdx': 0, 'mastery': 'slow',
    })
    r = client.get('/api/sentence/mastery/a')
    assert r.json['mastery']['0']['0']['mastery'] == 'fluent', 'fluent 不该被 slow 覆盖'


def test_mastery_invalid_rejected(client):
    r = client.post('/api/sentence/mastery', json={
        'bookId': 'a', 'chapterIdx': 0, 'sentenceIdx': 0, 'mastery': 'invalid',
    })
    assert r.json['success'] is False


def test_mastery_accumulates_attempts(tmp_db, client):
    """多次 attempted, attempts 累加"""
    for _ in range(3):
        client.post('/api/sentence/mastery', json={
            'bookId': 'a', 'chapterIdx': 0, 'sentenceIdx': 0, 'mastery': 'attempted',
        })
    r = client.get('/api/sentence/mastery/a')
    assert r.json['mastery']['0']['0']['attempts'] == 3


# === 旧数据兼容: 没 R12 字段也能 load ===
def test_load_old_data_backfills_new_sections(tmp_db):
    """_load_parent_data 碰到老 JSON (只有 stats/vocabulary/settings) 应该补齐 R12 字段"""
    from extensions.db import get_db
    import json as json_mod
    conn = get_db()
    conn.execute(
        'INSERT OR REPLACE INTO parent_data (id, data_json, updated_at) VALUES (1, ?, ?)',
        (json_mod.dumps({"stats": {"x": 1}, "vocabulary": {}, "settings": {}}, ensure_ascii=False),
         int(time.time() * 1000)),
    )
    data = parent_data._load_parent_data()
    assert 'vocabReviews' in data
    assert 'bookProgress' in data
    assert 'sentenceMastery' in data
    assert data['stats']['x'] == 1, '老数据应该保留'