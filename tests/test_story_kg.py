"""Magic Tree House 章节 → 知识点映射。

守的是三条不能退化的性质:

1. **章节名要跟前端对得上**。tutor.js 里的 mth29Chapters 是手抄的正文选段,
   映射按名字索引;而且前端是按**序号**去 API 的 units 里取的
   (`loadUnitKnowledge(chapterId, 'mth29')`),所以两边的**顺序**也必须一样。
   顺序错了 → 显示的是隔壁那章的知识点,而且不报错,最难查。
2. **知识点必须是真的**。key 拼错 → 界面上的标签空掉;写了图谱里
   没有的点 → 静默丢掉,映射就少了一条。
3. **每章都要有映射**。少一章 → 那一章的知识点条整个不显示。
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions import story_kg                        # noqa: E402
from extensions.kg import GRAMMAR_NODES, course_unit_graph  # noqa: E402

TUTOR_JS = ROOT / 'web' / 'js' / 'tutor.js'


def _js_chapter_names() -> list:
    """从 tutor.js 里抠出 mth29Chapters 的章节名(按出现顺序)。"""
    src = TUTOR_JS.read_text(encoding='utf-8')
    start = src.index('const mth29Chapters = [')
    i = src.index('[', start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '[':
            depth += 1
        elif src[j] == ']':
            depth -= 1
            if depth == 0:
                break
    block = src[i:j + 1]
    return re.findall(r'\{\s*name:\s*"([^"]+)"', block)


def test_chapter_names_match_tutor_js_exactly():
    """名字对不上 → 前端永远拿不到这一章的映射。"""
    assert list(story_kg.MTH_CHAPTER_KG.keys()) == _js_chapter_names()


def test_chapter_order_matches_tutor_js_exactly():
    """顺序对不上 → 显示的是隔壁那章的知识点,而且不报错。"""
    js_names = _js_chapter_names()
    kg_names = list(story_kg.MTH_CHAPTER_KG.keys())
    assert kg_names == js_names, \
        f'顺序不一致:\n  js  = {js_names}\n  kg  = {kg_names}'


def test_every_chapter_has_a_mapping():
    assert len(story_kg.MTH_CHAPTER_KG) == 7
    for name, keys in story_kg.MTH_CHAPTER_KG.items():
        assert keys, f'{name} 没有映射知识点'


def test_all_keys_exist_in_graph():
    """写了图谱里没有的 key → 静默丢掉,映射少一条。"""
    for name, keys in story_kg.MTH_CHAPTER_KG.items():
        for k in keys:
            assert k in GRAMMAR_NODES, f'{name} 里的 {k} 不在 GRAMMAR_NODES'


def test_no_duplicate_keys_in_a_chapter():
    for name, keys in story_kg.MTH_CHAPTER_KG.items():
        assert len(keys) == len(set(keys)), f'{name} 有重复的知识点'


def test_chapter_is_not_overloaded():
    """一屏 4 个点以内,多了就成了知识点清单,孩子看不完。"""
    for name, keys in story_kg.MTH_CHAPTER_KG.items():
        assert len(keys) <= 4, f'{name} 知识点太多: {keys}'


def test_every_chapter_has_a_note():
    """给家长看的这一章在干什么,每章都要有一句。"""
    for name in story_kg.MTH_CHAPTER_KG:
        assert story_kg.MTH_CHAPTER_NOTE.get(name, '').strip(), f'{name} 没有说明'


def test_course_graph_serves_mth29():
    units = course_unit_graph('mth29')
    assert len(units) == 7
    for u in units:
        assert u['grammar'], f'{u["name"]} 没返回知识点'
        assert all('label' in g and g['label'] for g in u['grammar'])
        assert u['name'] in story_kg.MTH_CHAPTER_KG


def test_course_graph_blocked_are_valid_and_not_in_grammar():
    for u in course_unit_graph('mth29'):
        own = {g['key'] for g in u['grammar']}
        for b in u['blocked']:
            assert b['key'] in GRAMMAR_NODES
            assert b['key'] not in own, \
                f'{u["name"]} 的前置里混进了它自己已经会的点'


def test_unknown_course_returns_empty():
    assert course_unit_graph('nope') == []


def test_nc2a_still_works():
    """教材那条路不能被这次改动弄坏。"""
    units = course_unit_graph('nc2a')
    assert len(units) == 9
    assert any(u['grammar'] for u in units)
