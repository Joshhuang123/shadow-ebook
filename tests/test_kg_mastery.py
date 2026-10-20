"""掌握度:图谱唯一的数据来源。

之前 `kg_mastery` 表建好了、`learning_path()` 也会读它,但**没有任何东西往里写** ——
所以「下一个该练什么」一直等于按拓扑深度全量推荐,不是诊断。

现在接上了语法练习的成绩。这几条守的是它不能退化的几条性质:

1. 练一次要对:8/8 → mastered;2/6 → learning
2. **后来的差成绩不能抹掉之前的好成绩** —— 孩子上次 100%、这次 40%,
   不该被判成「没掌握」。遗忘靠衰减,不是靠「记最差的那次」。
3. 教材讲解页的 key(present-progressive)要记到对应的图谱节点上
4. 掌握强度要**随时间衰减** —— 三个月前会的东西,不该今天还记着「已掌握」。
   这是图谱「活」起来的关键:它得反映孩子**现在**会什么。
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions import kg              # noqa: E402
from extensions.db import get_db       # noqa: E402


@pytest.fixture
def client(tmp_db):
    import importlib
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


@pytest.fixture(autouse=True)
def _clean_mastery(tmp_db):
    """每个用例从「什么都没练过」开始。

    依赖 tmp_db:不依赖的话,这个清理会写到**生产库**,
    把家长孩子的真实掌握度抹掉。
    """
    get_db().execute('DELETE FROM kg_mastery')
    get_db().commit()
    yield
    get_db().execute('DELETE FROM kg_mastery')
    get_db().commit()


def _state(key):
    row = get_db().execute(
        'SELECT state, strength FROM kg_mastery WHERE node_id = ?',
        (f'grammar:{key}',)).fetchone()
    return (row['state'], round(row['strength'], 4)) if row else (None, 0.0)


# === 写入 ===

def test_perfect_score_is_mastered():
    kg.record_mastery([{'key': 'ket-present-simple', 'correct': 8, 'total': 8}])
    state, strength = _state('ket-present-simple')
    assert state == 'mastered'
    assert strength == 1.0


def test_mediocre_score_is_familiar():
    kg.record_mastery([{'key': 'ket-there-be', 'correct': 6, 'total': 8}])
    state, strength = _state('ket-there-be')
    assert state == 'familiar', '75% 应该是「基本会了」'
    assert 0.7 < strength < 0.8


def test_bad_score_is_learning():
    kg.record_mastery([{'key': 'ket-present-continuous', 'correct': 2, 'total': 6}])
    state, _ = _state('ket-present-continuous')
    assert state == 'learning'


def test_worse_later_result_does_not_demote():
    """上次 100%、这次 40% —— 不能被降级。

    遗忘交给衰减处理(见 test_decay),不靠「记最差的那次」:
    孩子偶尔做错一套题,不代表他不会了。
    """
    kg.record_mastery([{'key': 'ket-modals', 'correct': 8, 'total': 8}])
    assert _state('ket-modals')[0] == 'mastered'
    kg.record_mastery([{'key': 'ket-modals', 'correct': 3, 'total': 8}])
    state, strength = _state('ket-modals')
    assert state == 'mastered', '一次差成绩把已掌握的点打回去了'
    assert strength == 1.0, '强度应该保留最好成绩'


def test_better_result_improves():
    kg.record_mastery([{'key': 'ket-modals', 'correct': 3, 'total': 8}])
    kg.record_mastery([{'key': 'ket-modals', 'correct': 8, 'total': 8}])
    state, strength = _state('ket-modals')
    assert state == 'mastered'
    assert strength == 1.0


def test_alias_key_maps_to_graph_node():
    """语法页的「教材讲解页」key 要记到对应的图谱节点上。"""
    kg.record_mastery([{'key': 'present-progressive', 'correct': 4, 'total': 4}])
    assert _state('ket-present-continuous')[0] == 'mastered'


def test_alias_with_several_targets():
    """possessive-pronouns 对应两个点,两个都要记。"""
    kg.record_mastery([{'key': 'possessive-pronouns', 'correct': 4, 'total': 4}])
    assert _state('ket-possessive')[0] == 'mastered'
    assert _state('ket-pronouns')[0] == 'mastered'


def test_unknown_key_is_skipped_not_crashed():
    res = kg.record_mastery([{'key': 'no-such-point', 'correct': 1, 'total': 1}])
    assert res['written'] == []
    assert res['skipped'] == ['no-such-point']


def test_invalid_numbers_are_skipped():
    res = kg.record_mastery([
        {'key': 'ket-modals', 'correct': 5, 'total': 0},      # 分母 0
        {'key': 'ket-modals', 'correct': 9, 'total': 4},      # 正确数 > 总数
        {'key': 'ket-modals', 'correct': -1, 'total': 4},     # 负数
        'not-a-dict',
    ])
    assert res['written'] == []
    assert len(res['skipped']) == 4


def test_practising_with_zero_correct_still_records():
    """练过但全错,也要留下记录 ——
    「没练过」和「练过但不会」给家长的建议完全不同。"""
    kg.record_mastery([{'key': 'ket-imperative', 'correct': 0, 'total': 5}])
    state, strength = _state('ket-imperative')
    assert state == 'learning'
    assert strength == 0.0


# === 衰减 ===

def test_strength_decays_over_time():
    """100 天前练对的,现在不该还是「已掌握」。"""
    kg.record_mastery([{'key': 'ket-modals', 'correct': 8, 'total': 8}])
    assert _state('ket-modals')[0] == 'mastered'

    # 把这条记录的时间戳改到 100 天前
    old_ts = int((time.time() - 100 * 86400) * 1000)
    get_db().execute('UPDATE kg_mastery SET updated_at = ?', (old_ts,))
    get_db().commit()

    summary = kg.mastery_summary()
    p = next(x for x in summary['points'] if x['key'] == 'ket-modals')
    assert p['state'] != 'mastered', '100 天前的掌握还记着,图谱就没活起来'
    assert p['strength'] < 1.0


def test_half_life_halves_strength():
    """半衰期过了,强度减半。"""
    kg.record_mastery([{'key': 'ket-modals', 'correct': 8, 'total': 8}])
    half = kg.MASTERY_HALF_LIFE_DAYS
    ts = int((time.time() - half * 86400) * 1000)
    get_db().execute('UPDATE kg_mastery SET updated_at = ?', (ts,))
    get_db().commit()
    p = next(x for x in kg.mastery_summary()['points'] if x['key'] == 'ket-modals')
    assert 0.4 < p['strength'] < 0.6, f'半衰期后强度应约 0.5,实际 {p["strength"]}'


def test_recent_practice_stays_mastered():
    """刚练过的不该被衰减掉。"""
    kg.record_mastery([{'key': 'ket-modals', 'correct': 8, 'total': 8}])
    p = next(x for x in kg.mastery_summary()['points'] if x['key'] == 'ket-modals')
    assert p['state'] == 'mastered'


# === 汇总与联动 ===

def test_mastery_summary_counts():
    kg.record_mastery([
        {'key': 'ket-present-simple', 'correct': 8, 'total': 8},    # mastered
        {'key': 'ket-there-be', 'correct': 6, 'total': 8},         # familiar
        {'key': 'ket-modals', 'correct': 1, 'total': 6},           # learning
    ])
    s = kg.mastery_summary()
    assert s['total'] == len(kg.GRAMMAR_NODES)
    assert s['counts']['mastered'] == 1
    assert s['counts']['familiar'] == 1
    assert s['counts']['learning'] == 1
    assert s['counts']['not-started'] == s['total'] - 3


def test_learning_path_respects_mastery():
    """练过的点不再出现在「下一个该练什么」里。"""
    kg.record_mastery([{'key': 'ket-there-be', 'correct': 8, 'total': 8}])
    path = kg.learning_path(limit=6)
    assert 'ket-there-be' not in [p['key'] for p in path], \
        '已经掌握的点还在推荐列表里'


def test_gaps_respects_mastery():
    """掌握的点不再算成「前置缺口」。"""
    kg.record_mastery([{'key': 'ket-pronouns', 'correct': 8, 'total': 8}])
    gaps = kg.gaps()
    assert 'grammar:ket-pronouns' not in [g['id'] for g in gaps]


# === HTTP 接口 ===

def test_mastery_api_roundtrip(client):
    r = client.post('/api/kg/mastery', json={
        'items': [{'key': 'ket-present-simple', 'correct': 8, 'total': 8}]})
    assert r.get_json()['success']
    g = client.get('/api/kg/mastery').get_json()
    assert g['success']
    assert g['counts']['mastered'] == 1


def test_mastery_api_rejects_empty(client):
    r = client.post('/api/kg/mastery', json={})
    assert r.status_code == 400
