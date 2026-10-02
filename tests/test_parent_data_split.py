"""R22 拆表: parent_data 单行 blob → parent_section / vocab_reviews /
book_progress / sentence_mastery。

之前全部学习数据塞在单行 JSON 里,阅读器每读一句、每次查词都是
read-modify-write 整个 blob —— O(全量), gunicorn 多 worker 下还会
last-write-wins 互相覆盖。拆表后热路径全部单行 UPSERT。

本文件钉住:
  - 新表随 init_db 建出来
  - 旧 blob 一次性迁入, 形状与拆表前逐键一致; 迁移幂等; 坏 blob 不炸
  - 热路径真的落在行级表上 (而不是又偷偷写回整 blob)
  - write_txn 出错回滚, 不留半截写
"""
import importlib
import json
import time

import pytest

from extensions import db, parent_data


@pytest.fixture
def client(tmp_db, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


def _table_names() -> set:
    conn = db.get_db()
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _count(table: str) -> int:
    return db.get_db().execute(f'SELECT COUNT(*) AS c FROM {table}').fetchone()['c']


# === schema ===

def test_init_db_creates_split_tables(tmp_db):
    tables = _table_names()
    for t in ('parent_section', 'vocab_reviews', 'book_progress', 'sentence_mastery'):
        assert t in tables, f'拆表后的新表 {t} 没建出来'


# === 迁移 ===

def _old_blob() -> dict:
    now = int(time.time() * 1000)
    return {
        "stats": {"todayMinutes": 25, "days": {"2026-10-01": 25}},
        "vocabulary": {"lookedWords": {"apple": True}, "newWords": {"kiwi": True}},
        "settings": {"fontSize": 20, "child": {"name": "小明", "age": 8, "lexile": 600}},
        "vocabReviews": {
            "apple": {"state": "practicing", "added_ts": now, "next_review_ts": now + 100,
                      "last_review_ts": now, "review_count": 3, "correct_count": 2},
        },
        "bookProgress": {"hp1": {"chapter_idx": 2, "sentence_idx": 5, "last_open_ts": now}},
        "sentenceMastery": {"hp1": {"0": {"5": {
            "mastery": "fluent", "attempts": 2, "last_attempt_ts": now}}}},
    }


def _seed_old_blob(blob: dict):
    conn = db.get_db()
    conn.execute(
        'INSERT OR REPLACE INTO parent_data (id, data_json, updated_at) VALUES (1, ?, ?)',
        (json.dumps(blob, ensure_ascii=False), int(time.time() * 1000)),
    )


def _rerun_split_migration(tmp_db):
    """模拟旧部署首启: 删 marker 重跑 init_db 的拆表段。"""
    marker = tmp_db / '.parent_split_migrated'
    if marker.exists():
        marker.unlink()
    db.init_db()


def test_split_migration_preserves_every_section(tmp_db):
    blob = _old_blob()
    _seed_old_blob(blob)
    _rerun_split_migration(tmp_db)

    loaded = parent_data._load_parent_data()
    assert loaded['stats'] == blob['stats']
    assert loaded['vocabulary'] == blob['vocabulary']
    assert loaded['settings'] == blob['settings']
    assert loaded['vocabReviews']['apple']['state'] == 'practicing'
    assert loaded['vocabReviews']['apple']['review_count'] == 3
    assert loaded['bookProgress']['hp1']['chapter_idx'] == 2
    # sentenceMastery 嵌套键进了表, 读出来是字符串键 (JSON 形状不变)
    assert loaded['sentenceMastery']['hp1']['0']['5']['mastery'] == 'fluent'
    assert loaded['sentenceMastery']['hp1']['0']['5']['attempts'] == 2


def test_split_migration_keeps_old_row_as_snapshot(tmp_db):
    """旧 blob 行保留不删 —— 拆表前快照, 新代码不读它, 但出问题能回捞。"""
    _seed_old_blob(_old_blob())
    _rerun_split_migration(tmp_db)
    row = db.get_db().execute('SELECT data_json FROM parent_data WHERE id = 1').fetchone()
    assert row is not None, '旧 blob 快照不该被删'


def test_split_migration_is_idempotent(tmp_db):
    """重跑迁移不重复灌数据 (PK + INSERT OR IGNORE + marker)。"""
    _seed_old_blob(_old_blob())
    _rerun_split_migration(tmp_db)
    _rerun_split_migration(tmp_db)
    assert _count('vocab_reviews') == 1
    assert _count('book_progress') == 1
    assert _count('sentence_mastery') == 1
    assert _count('parent_section') == 3


def test_split_migration_survives_corrupt_blob(tmp_db):
    """坏 blob 只 warning 不炸 —— 启动不能因为一份坏数据挂掉。"""
    _seed_old_blob({})  # 占位,下面覆盖成非法 JSON
    db.get_db().execute(
        'UPDATE parent_data SET data_json = ? WHERE id = 1',
        ('{not valid json',),
    )
    _rerun_split_migration(tmp_db)  # 不抛异常即通过
    assert parent_data._load_parent_data()['stats'] == {}


# === 热路径真的写在行级表上 ===

def test_vocab_lookup_lands_in_vocab_reviews_table(tmp_db):
    parent_data._record_vocab_lookup('Apple')
    assert _count('vocab_reviews') == 1
    row = db.get_db().execute("SELECT * FROM vocab_reviews WHERE word = 'apple'").fetchone()
    assert row['state'] == 'learning'
    assert row['review_count'] == 0
    # lookedWords 兼容行为还在: vocabulary section 里也标了
    assert parent_data._load_section('vocabulary')['lookedWords']['apple'] is True


def test_progress_upserts_single_row_per_book(client):
    client.post('/api/progress', json={'bookId': 'hp1', 'chapterIdx': 1, 'sentenceIdx': 0})
    client.post('/api/progress', json={'bookId': 'hp1', 'chapterIdx': 1, 'sentenceIdx': 9})
    assert _count('book_progress') == 1, '同本书两次上报应是 UPSERT 一行, 不是两行'
    r = client.get('/api/progress/hp1')
    assert r.json['progress']['sentence_idx'] == 9


def test_sentence_mastery_lands_in_table_with_fluent_lock(client):
    client.post('/api/sentence/mastery', json={
        'bookId': 'a', 'chapterIdx': 0, 'sentenceIdx': 0, 'mastery': 'fluent'})
    client.post('/api/sentence/mastery', json={
        'bookId': 'a', 'chapterIdx': 0, 'sentenceIdx': 0, 'mastery': 'slow'})
    row = db.get_db().execute(
        'SELECT * FROM sentence_mastery WHERE book_id = ? AND chapter_idx = 0 AND sentence_idx = 0',
        ('a',)).fetchone()
    assert row['mastery'] == 'fluent', 'fluent 锁要落在行级数据上'
    assert row['attempts'] == 1, '被 fluent 锁挡下的上报不该累计 attempts'


def test_reset_clears_all_split_tables(client):
    parent_data._record_vocab_lookup('apple')
    client.post('/api/progress', json={'bookId': 'hp1', 'chapterIdx': 0, 'sentenceIdx': 0})
    client.post('/api/parent/data', json={'stats': {'todayMinutes': 9}})
    # reset 要家长鉴权, 这里直接开一个已登录会话
    with client.session_transaction() as s:
        s['parent_auth'] = True
    r = client.post('/api/parent/reset')
    assert r.json['success'] is True
    assert _count('vocab_reviews') == 0
    assert _count('book_progress') == 0
    assert _count('sentence_mastery') == 0
    assert _count('parent_section') == 0


# === write_txn ===

def test_write_txn_rolls_back_on_error(tmp_db):
    """事务里第二条写失败 → 第一条也不能留下。"""
    with pytest.raises(ValueError):
        with db.write_txn() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO book_progress (book_id, chapter_idx, sentence_idx, last_open_ts) '
                "VALUES ('boom', 0, 0, 0)")
            raise ValueError('模拟中途出错')
    assert _count('book_progress') == 0, '回滚后的半截写不该残留'


def test_parent_data_get_returns_full_shape(client):
    client.post('/api/vocab/lookup', json={'word': 'apple'})
    client.post('/api/progress', json={'bookId': 'hp1', 'chapterIdx': 0, 'sentenceIdx': 0})
    client.post('/api/sentence/mastery', json={
        'bookId': 'hp1', 'chapterIdx': 0, 'sentenceIdx': 0, 'mastery': 'slow'})
    client.post('/api/parent/data', json={'stats': {'todayMinutes': 5}})

    # 家长 dashboard 的读取入口不变
    data = parent_data._load_parent_data()
    assert set(data) == {'stats', 'vocabulary', 'settings',
                         'vocabReviews', 'bookProgress', 'sentenceMastery'}
    assert data['vocabReviews']['apple']['state'] == 'learning'
    assert data['bookProgress']['hp1']['sentence_idx'] == 0
    assert data['sentenceMastery']['hp1']['0']['0']['mastery'] == 'slow'
