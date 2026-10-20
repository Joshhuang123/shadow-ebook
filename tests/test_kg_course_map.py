"""教材单元 / 考试考纲 ↔ 知识图谱的对照。

2026-10-20 补:之前图谱是「悬空」的 —— 24 个语法点和它们的��置关系都有,
但**没有跟孩子实际在学的东西连起来**。于是「孩子在第 3 单元卡住 →
是哪个前置没会」这条链算不出来,家长看到��只是「英语不好」。

现在加了两层对照:
  · 教材单元 → 知识点(courses.py 里每个单元的 kg 字段,跟着内容走)
  · 考试考纲 → 知识点(小托福 / 剑桥通用五级)

这些映射是**手工维护**的,理由和 GRAMMAR_PREREQS 一样:
「这个单元教什么」「这场考试考什么」是教材和考纲的事实,算不出来。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions import courses          # noqa: E402
from extensions import kg              # noqa: E402


# === 教材单元 → 知识点 ===

def test_every_course_unit_has_kg_mapping():
    """每个单元都要说清楚它对应哪些知识点 —— 不然图谱跟教材还是两张皮。"""
    units = courses.COURSE_CONTENT['units']
    assert units, '课程内容空了'
    missing = [u.get('name') for u in units if not u.get('kg')]
    assert not missing, f'这些单元没写知识点映射: {missing}'


def test_course_unit_kg_keys_all_exist():
    """映射里的每个 key 都得是真实的节点,不能指向不存在的点。"""
    for unit in courses.COURSE_CONTENT['units']:
        for key in (unit.get('kg') or []):
            assert key in kg.GRAMMAR_NODES, \
                f'单元「{unit["name"]}」指向了不存在的知识点 {key}'


def test_course_unit_graph_shape():
    """每个单元都要给出:知识点 + 缺的前置。"""
    units = kg.course_unit_graph('nc2a')
    assert len(units) == len(courses.COURSE_CONTENT['units'])
    for u in units:
        assert u['grammar'], f'单元 {u["name"]} 没有知识点'
        for g in u['grammar']:
            assert g['label'] and g['level']
        for b in u['blocked']:
            assert b['key'] in kg.GRAMMAR_NODES


def test_course_unit_blocked_is_the_real_prereq():
    """「缺的前置」必须真的是它的前置,不能是别的点。"""
    units = {u['name']: u for u in kg.course_unit_graph('nc2a')}
    u = units['Unit 1-2: 现在进行时']
    own = {g['key'] for g in u['grammar']}
    expected = set()
    for k in own:
        expected |= set(kg.GRAMMAR_PREREQS.get(k, []))
    expected -= own
    assert {b['key'] for b in u['blocked']} == expected


def test_course_unit_blocked_excludes_own_points():
    """单元自己的点不能同时被算成「缺的前置」。"""
    for u in kg.course_unit_graph('nc2a'):
        own = {g['key'] for g in u['grammar']}
        for b in u['blocked']:
            assert b['key'] not in own, \
                f'单元「{u["name"]}」把自己的点算成了缺的前置'


def test_unknown_course_returns_empty():
    assert kg.course_unit_graph('no-such-course') == []


# === 考试考纲 → 知识点 ===

def test_both_exam_scopes_exist():
    """小托福和剑桥通用五级都要有对照。"""
    assert 'toefl_junior' in kg.EXAM_SCOPES
    assert 'cambridge_gkt' in kg.EXAM_SCOPES


def test_exam_scope_keys_all_exist():
    for exam_id, scope in kg.EXAM_SCOPES.items():
        for area in scope['areas']:
            for key in area['grammar']:
                assert key in kg.GRAMMAR_NODES, \
                    f'{exam_id} 的 {area["name"]} 指向了不存在的知识点 {key}'


def test_exam_scope_has_areas_and_labels():
    for exam_id, scope in kg.EXAM_SCOPES.items():
        assert scope['name']
        assert scope['note'], f'{exam_id} 缺 note —— 要说清这不是官方考纲'
        assert scope['areas'], f'{exam_id} 没有类目'
        for area in scope['areas']:
            assert area['name']
            assert area['grammar']


def test_exam_scope_blocked_is_the_real_prereq():
    """考纲类目里「缺的前置」= 该类目所有点的前置减去类目内部的点。"""
    for exam_id in kg.EXAM_SCOPES:
        scope = kg.exam_scope(exam_id)
        for area in scope['areas']:
            own = {g['key'] for g in area['grammar']}
            expected = set()
            for k in own:
                expected |= set(kg.GRAMMAR_PREREQS.get(k, []))
            expected -= own
            assert {b['key'] for b in area['blocked']} == expected, \
                f'{exam_id} / {area["name"]} 的前置缺口算错了'


def test_exam_scope_blocked_excludes_own_points():
    for exam_id in kg.EXAM_SCOPES:
        for area in kg.exam_scope(exam_id)['areas']:
            own = {g['key'] for g in area['grammar']}
            for b in area['blocked']:
                assert b['key'] not in own


def test_toefl_junior_covers_the_four_skill_areas():
    """小托福的四个类目是公开的,不能漏。"""
    scope = kg.exam_scope('toefl_junior')
    names = ' '.join(a['name'] for a in scope['areas'])
    for kw in ('阅读', '听力', '口语', '写作'):
        assert kw in names, f'小托福对照缺了「{kw}」'


def test_unknown_exam_returns_empty():
    assert kg.exam_scope('no-such-exam') == {}


# === 和教材内容的一致性 ===

def test_unit_grammar_notes_match_kg_keys():
    """课程里每句话自己标的 grammar,应该和单元的 kg 映射指向同一个点。

    不要求完全一致(一句话可能涉及多个点),但**不能完全没有交集** ——
    完全没交集说明映射写错了单元。
    """
    for unit in courses.COURSE_CONTENT['units']:
        notes = ' '.join((s.get('grammar') or '') for s in unit['sentences'])
        labels = ' '.join(
            kg.GRAMMAR_NODES[k][0] for k in (unit.get('kg') or []))
        # 至少一个关键词对得上
        hits = [w for w in ('现在进行时', '一般现在时', '频率', 'be going to',
                            'want to', '一般过去时', '祈使句', '物主代词',
                            '不定式', '所有格', '第三人称单数')
                if w in notes]
        if hits:
            assert any(w in labels or w in notes for w in hits), \
                f'单元「{unit["name"]}」的句子标了 {hits}，但知识点映射是 {labels}'


def test_kg_prereqs_stay_acyclic_after_mapping():
    """加了教材映射之后,前置图仍然不能有环。"""
    def depth(key, seen=None):
        seen = seen or set()
        if key in seen:
            raise AssertionError(f'前置图有环: {key}')
        seen = seen | {key}
        return 1 + max([depth(p, seen) for p in kg.GRAMMAR_PREREQS.get(key, [])]
                       or [0])

    for key in kg.GRAMMAR_NODES:
        depth(key)
